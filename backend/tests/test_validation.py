"""Validation acceptance tests (FEAT-002).

Covers the strict contract, plausibility flagging (never trusted, never used to
lower status), sensor_status normalization, timestamp-skew flagging, dedup_key
idempotency, and preservation of the simulated flag through validation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.config import load_config
from app.core.db import create_all, make_engine, make_session_factory
from app.core.models_db import Reading
from app.core.schemas import ReadingIn
from app.ingestion.validator import (
    FLAG_INVALID_TIMESTAMP,
    FLAG_OK,
    FLAG_OUT_OF_RANGE,
    ContractError,
    validate_reading,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def clinical():
    cfg = load_config()
    assert cfg.loaded, f"config failed to load: {cfg.load_error}"
    return cfg.clinical


def _payload(**overrides):
    base = {
        "device_id": "dev-1",
        "wound_id": "wound-1",
        "ts": NOW.isoformat(),
        "ph": 7.1,
        "skin_temp_c": 32.5,
        "moisture_pct": 50.0,
        "battery_pct": 90.0,
        "sensor_status": "ok",
    }
    base.update(overrides)
    return base


# -- strict contract (extra='forbid') -------------------------------------


def test_reading_in_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ReadingIn(**_payload(forced_level="normal"))


def test_dose_request_in_rejects_unknown_fields():
    from app.core.schemas import DoseRequestIn

    with pytest.raises(ValidationError):
        DoseRequestIn(requested_dose_mj=50, requested_duration_s=60, max_dose_mj=9999)


# -- missing / wrong-type -> rejected with offending field(s) --------------


def test_missing_field_rejected_with_field_name(clinical):
    payload = _payload()
    del payload["ph"]
    with pytest.raises(ContractError) as exc:
        validate_reading(payload, clinical, source="http", simulated=False, now=NOW)
    assert "ph" in exc.value.fields


def test_wrong_type_rejected_with_field_name(clinical):
    payload = _payload(ph="not-a-number")
    with pytest.raises(ContractError) as exc:
        validate_reading(payload, clinical, source="http", simulated=False, now=NOW)
    assert "ph" in exc.value.fields


def test_bool_is_not_accepted_as_number(clinical):
    payload = _payload(moisture_pct=True)
    with pytest.raises(ContractError) as exc:
        validate_reading(payload, clinical, source="http", simulated=False, now=NOW)
    assert "moisture_pct" in exc.value.fields


# -- plausibility flagging: never trusted, cannot lower status -------------


def test_out_of_range_value_is_flagged_not_rejected(clinical):
    # ph 20 is outside plausible 0..14 -> flagged, still returned (persisted).
    r = validate_reading(_payload(ph=20.0), clinical, source="http", simulated=False, now=NOW)
    assert r.field_flags["ph"] == FLAG_OUT_OF_RANGE
    assert r.ph == 20.0  # value preserved, not silently coerced


def test_flagged_value_marked_not_usable(clinical):
    r = validate_reading(_payload(ph=20.0), clinical, source="http", simulated=False, now=NOW)
    # has_usable is what the engine checks before letting a value LOWER status.
    assert r.has_usable("ph") is False
    assert r.has_usable("skin_temp_c") is True


def test_in_range_values_flagged_ok(clinical):
    r = validate_reading(_payload(), clinical, source="http", simulated=False, now=NOW)
    for metric in ("ph", "skin_temp_c", "moisture_pct", "battery_pct"):
        assert r.field_flags[metric] == FLAG_OK


# -- sensor_status normalization ------------------------------------------


def test_unknown_sensor_status_becomes_disconnected_with_warning(clinical):
    r = validate_reading(
        _payload(sensor_status="garbled"), clinical, source="http", simulated=False, now=NOW
    )
    assert r.sensor_status == "disconnected"
    assert any("sensor_status" in w for w in r.warnings)


def test_known_sensor_status_preserved(clinical):
    r = validate_reading(
        _payload(sensor_status="drifting"), clinical, source="http", simulated=False, now=NOW
    )
    assert r.sensor_status == "drifting"
    assert r.warnings == []


# -- future ts beyond skew -> invalid_timestamp ----------------------------


def test_future_ts_beyond_skew_flagged(clinical):
    future = (NOW + timedelta(seconds=clinical.clock_skew_tolerance_s + 60)).isoformat()
    r = validate_reading(_payload(ts=future), clinical, source="http", simulated=False, now=NOW)
    assert r.field_flags["ts"] == FLAG_INVALID_TIMESTAMP


def test_ts_within_skew_ok(clinical):
    near = (NOW + timedelta(seconds=clinical.clock_skew_tolerance_s - 1)).isoformat()
    r = validate_reading(_payload(ts=near), clinical, source="http", simulated=False, now=NOW)
    assert r.field_flags["ts"] == FLAG_OK


# -- simulated flag preserved through validation ---------------------------


def test_simulated_flag_preserved(clinical):
    r = validate_reading(_payload(), clinical, source="simulator", simulated=True, now=NOW)
    assert r.simulated is True
    assert r.source == "simulator"


def test_simulated_false_for_real_source(clinical):
    r = validate_reading(_payload(), clinical, source="serial", simulated=False, now=NOW)
    assert r.simulated is False
    assert r.source == "serial"


# -- dedup_key built and dedups idempotently at the DB layer ---------------


def test_dedup_key_shape(clinical):
    r = validate_reading(_payload(), clinical, source="http", simulated=False, now=NOW)
    assert r.dedup_key == f"dev-1|wound-1|{r.ts.isoformat()}"


def test_duplicate_dedup_key_rejected_idempotently(clinical):
    engine = make_engine("sqlite://")
    create_all(engine)
    session = make_session_factory(engine)()
    try:
        r = validate_reading(_payload(), clinical, source="http", simulated=False, now=NOW)

        def _row():
            return Reading(
                device_id=r.device_id,
                wound_id=r.wound_id,
                ts=r.ts,
                ph=r.ph,
                skin_temp_c=r.skin_temp_c,
                moisture_pct=r.moisture_pct,
                battery_pct=r.battery_pct,
                sensor_status=r.sensor_status,
                source=r.source,
                simulated=r.simulated,
                field_flags=r.field_flags,
                dedup_key=r.dedup_key,
            )

        session.add(_row())
        session.commit()

        session.add(_row())  # same dedup_key
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()
        engine.dispose()
