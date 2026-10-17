"""DB schema acceptance tests (FEAT-001).

Proves all tables create in an in-memory SQLite DB, a reading round-trips, and
the UNIQUE(dedup_key) constraint rejects a duplicate.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.core.db import create_all, make_engine, make_session_factory
from app.core.models_db import (
    AuditLog,
    Device,
    DoseRequest,
    Reading,
    ReportedSymptom,
    Status,
    Wound,
)


@pytest.fixture()
def session():
    engine = make_engine("sqlite://")  # shared in-memory
    create_all(engine)
    factory = make_session_factory(engine)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def test_all_tables_create(session) -> None:
    inspector = inspect(session.get_bind())
    tables = set(inspector.get_table_names())
    expected = {
        "devices",
        "wounds",
        "reported_symptoms",
        "readings",
        "statuses",
        "dose_requests",
        "audit_log",
    }
    assert expected.issubset(tables)


def _make_reading(dedup_key: str = "dev-1|wound-1|2026-01-01T00:00:00Z") -> Reading:
    return Reading(
        device_id="dev-1",
        wound_id="wound-1",
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ph=7.2,
        skin_temp_c=33.1,
        moisture_pct=55.0,
        battery_pct=90.0,
        sensor_status="ok",
        source="simulator",
        simulated=True,
        field_flags={"ph": "ok", "skin_temp_c": "ok"},
        dedup_key=dedup_key,
    )


def test_reading_inserts_and_queries_back(session) -> None:
    session.add(_make_reading())
    session.commit()

    rows = session.execute(select(Reading)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.device_id == "dev-1"
    assert row.wound_id == "wound-1"
    assert row.simulated is True
    assert row.field_flags == {"ph": "ok", "skin_temp_c": "ok"}
    assert row.source == "simulator"


def test_duplicate_dedup_key_rejected(session) -> None:
    session.add(_make_reading())
    session.commit()

    session.add(_make_reading())  # same dedup_key
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_wound_unknown_attrs_are_nullable(session) -> None:
    session.add(Device(device_id="dev-1", label="demo"))
    session.add(
        Wound(
            wound_id="wound-1",
            device_id="dev-1",
            body_site="forearm",
            depth_type="partial",
            # attr_diabetic / attr_immunocompromised omitted => NULL => unknown
        )
    )
    session.commit()
    wound = session.get(Wound, "wound-1")
    assert wound is not None
    assert wound.attr_diabetic is None
    assert wound.attr_immunocompromised is None


def test_supporting_tables_accept_rows(session) -> None:
    session.add(Device(device_id="dev-1"))
    session.add(Wound(wound_id="wound-1", device_id="dev-1"))
    session.add(
        ReportedSymptom(
            wound_id="wound-1",
            ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
            kind="pus",
            present=True,
        )
    )
    session.add(
        Status(
            wound_id="wound-1",
            level="watch",
            data_level="watch",
            factors={"ph": "rising"},
            config_snapshot="sha256:abc",
        )
    )
    session.add(
        DoseRequest(
            wound_id="wound-1",
            requested_params={"requested_dose_mj": 50},
            outcome="granted",
            enforced_limits={"max_dose_mj": 100},
            granted_params={"dose_mj": 50},
            config_snapshot="sha256:abc",
        )
    )
    session.add(AuditLog(kind="status", wound_id="wound-1", payload={"level": "watch"}))
    session.commit()

    assert session.execute(select(ReportedSymptom)).scalars().first() is not None
    assert session.execute(select(Status)).scalars().first() is not None
    assert session.execute(select(DoseRequest)).scalars().first() is not None
    assert session.execute(select(AuditLog)).scalars().first() is not None
