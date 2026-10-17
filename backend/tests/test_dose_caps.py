"""Dose cap tests (FEAT-004) — one test per cap, deny-closed.

Exercises the pure ``app.safety.dose.decide`` for each cap plus the HTTP
endpoint for the grant-persists-params path and the escalate block.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import load_config
from app.core.schemas import DoseRequestIn
from app.safety import dose
from app.safety.dose import (
    OUTCOME_DENIED,
    OUTCOME_GRANTED,
    REASON_CONFIG_FAILSAFE,
    REASON_DAILY_CAP,
    REASON_ESCALATE,
    REASON_OVER_DOSE,
    REASON_OVER_SESSION,
    REASON_WITHIN_GAP,
)
from _helpers import reading_payload, seed_wound

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def cfg():
    c = load_config()
    assert c.loaded
    return c


@dataclass
class Grant:
    requested_at: datetime


NORMAL_STATUS = {"level": "normal", "red_flags": []}


def _req(dose_mj=10.0, duration_s=30.0) -> DoseRequestIn:
    return DoseRequestIn(requested_dose_mj=dose_mj, requested_duration_s=duration_s)


def test_over_dose_denied(cfg):
    over = cfg.dose.max_dose_mj + 1
    d = dose.decide("w", _req(dose_mj=over), [], NORMAL_STATUS, cfg, NOW)
    assert d.outcome == OUTCOME_DENIED
    assert d.reason_code == REASON_OVER_DOSE
    assert d.enforced_limits["max_dose_mj"] == cfg.dose.max_dose_mj


def test_over_session_denied(cfg):
    over = cfg.dose.max_session_s + 1
    d = dose.decide("w", _req(duration_s=over), [], NORMAL_STATUS, cfg, NOW)
    assert d.outcome == OUTCOME_DENIED
    assert d.reason_code == REASON_OVER_SESSION
    assert d.enforced_limits["max_session_s"] == cfg.dose.max_session_s


def test_within_gap_denied_returns_remaining_time(cfg):
    last = NOW - timedelta(seconds=cfg.dose.min_gap_s / 2)
    d = dose.decide("w", _req(), [Grant(last)], NORMAL_STATUS, cfg, NOW)
    assert d.outcome == OUTCOME_DENIED
    assert d.reason_code == REASON_WITHIN_GAP
    assert d.enforced_limits["remaining_gap_s"] > 0
    assert d.next_allowed_at is not None


def test_daily_cap_denied(cfg):
    # max_daily_sessions grants already today, all outside the gap window.
    grants = [
        Grant(NOW - timedelta(seconds=cfg.dose.min_gap_s * (i + 1)))
        for i in range(cfg.dose.max_daily_sessions)
    ]
    d = dose.decide("w", _req(), grants, NORMAL_STATUS, cfg, NOW)
    assert d.outcome == OUTCOME_DENIED
    assert d.reason_code == REASON_DAILY_CAP


def test_missing_status_blocks_deny_closed(cfg):
    # No status available => cannot confirm it is safe to dose => deny-closed.
    d = dose.decide("w", _req(), [], None, cfg, NOW)
    assert d.outcome == OUTCOME_DENIED
    assert d.reason_code == REASON_ESCALATE


def test_escalate_denied_with_care_direction(cfg):
    status = {"level": "escalate", "red_flags": ["RF_PUS"]}
    d = dose.decide("w", _req(), [], status, cfg, NOW)
    assert d.outcome == OUTCOME_DENIED
    assert d.reason_code == REASON_ESCALATE
    assert "care" in d.reason.lower()


def test_red_flag_active_denied(cfg):
    status = {"level": "watch", "red_flags": ["RF_FEVER"]}
    d = dose.decide("w", _req(), [], status, cfg, NOW)
    assert d.outcome == OUTCOME_DENIED
    assert d.reason_code == REASON_ESCALATE


def test_config_failsafe_denied(cfg):
    bad = load_config(clinical_path="missing.yaml", safety_path="missing.yaml")
    assert not bad.loaded
    d = dose.decide("w", _req(), [], None, bad, NOW)
    assert d.outcome == OUTCOME_DENIED
    assert d.reason_code == REASON_CONFIG_FAILSAFE
    assert d.config_failsafe is True


def test_granted_within_limits_persists_params(cfg):
    d = dose.decide(
        "w",
        _req(dose_mj=cfg.dose.max_dose_mj, duration_s=cfg.dose.max_session_s),
        [],
        {"level": "normal", "red_flags": []},
        cfg,
        NOW,
    )
    assert d.outcome == OUTCOME_GRANTED
    assert d.granted_params["dose_mj"] == cfg.dose.max_dose_mj
    assert d.granted_params["duration_s"] == cfg.dose.max_session_s
    assert "granted_at" in d.granted_params
    assert d.next_allowed_at == NOW + timedelta(seconds=cfg.dose.min_gap_s)


def test_grant_persists_via_endpoint(client, session_factory, cfg):
    seed_wound(session_factory)
    # A fresh normal reading so status does not block.
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    client.post("/readings", json=reading_payload(ts=_dt.now(_tz.utc)))

    resp = client.post(
        "/wounds/wound-1/dose-requests",
        json={"requested_dose_mj": 10.0, "requested_duration_s": 30.0},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["outcome"] == "granted"
    assert body["granted_params"]["dose_mj"] == 10.0
    assert body["next_allowed_at"] is not None

    # The grant is persisted as a dose_requests row.
    from app.core.models_db import DoseRequest

    s = session_factory()
    try:
        rows = s.query(DoseRequest).filter_by(wound_id="wound-1").all()
        assert len(rows) == 1
        assert rows[0].outcome == "granted"
        assert rows[0].granted_params["dose_mj"] == 10.0
    finally:
        s.close()


def test_over_dose_denied_via_endpoint_409(client, session_factory, cfg):
    seed_wound(session_factory)
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    client.post("/readings", json=reading_payload(ts=_dt.now(_tz.utc)))
    resp = client.post(
        "/wounds/wound-1/dose-requests",
        json={"requested_dose_mj": cfg.dose.max_dose_mj + 50, "requested_duration_s": 30.0},
    )
    assert resp.status_code == 409
    assert resp.json()["reason_code"] == REASON_OVER_DOSE


def test_dose_request_rejects_unknown_field(client, session_factory):
    seed_wound(session_factory)
    resp = client.post(
        "/wounds/wound-1/dose-requests",
        json={"requested_dose_mj": 10, "requested_duration_s": 30, "max_dose_mj": 99999},
    )
    assert resp.status_code == 422
