"""Audit-persistence tests (FEAT-003).

Acceptance: a status decision persists level/machine_code/factors/config_snapshot
and is reproducible from stored data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import load_config
from app.core.db import create_all, make_engine, make_session_factory
from app.core.models_db import AuditLog, Status
from app.safety import audit, rules

NOW = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def cfg():
    c = load_config()
    assert c.loaded
    return c


@pytest.fixture()
def session():
    engine = make_engine("sqlite://")
    create_all(engine)
    s = make_session_factory(engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@dataclass
class FakeReading:
    ts: datetime
    ph: float = 7.0
    skin_temp_c: float = 32.0
    moisture_pct: float = 45.0
    battery_pct: float = 95.0
    sensor_status: str = "ok"
    simulated: bool = False

    def has_usable(self, metric: str) -> bool:
        return True


def _history(cfg):
    # Infection-risk pH so the decision is interesting and non-normal.
    ph = cfg.clinical.ph_infection_risk_above + 0.2
    return [FakeReading(ts=NOW - timedelta(seconds=30), ph=ph)]


def test_status_decision_persists_fields(cfg, session):
    hist = _history(cfg)
    attrs = {"attr_diabetic": False, "attr_immunocompromised": False, "depth_type": "superficial"}
    result = rules.evaluate(hist, attrs, NOW, cfg, wound_id="wound-A")

    audit.persist_status(session, result, config_snapshot=cfg.config_snapshot, from_reading_id=42)
    session.commit()

    row = session.query(Status).one()
    assert row.wound_id == "wound-A"
    assert row.level == result.level
    assert row.machine_code == result.machine_code
    assert row.data_level == result.data_level
    assert row.sensor_health == result.sensor_health
    assert row.config_snapshot == cfg.config_snapshot
    assert row.from_reading_id == 42
    assert row.factors["level"] == result.level
    assert row.factors["machine_code"] == result.machine_code
    assert "trend" in row.factors


def test_audit_log_entry_written(cfg, session):
    result = rules.evaluate(_history(cfg), {}, NOW, cfg, wound_id="wound-B")
    audit.persist_status(session, result, config_snapshot=cfg.config_snapshot)
    session.commit()

    log = session.query(AuditLog).one()
    assert log.kind == "status"
    assert log.wound_id == "wound-B"
    assert log.payload["machine_code"] == result.machine_code
    assert log.payload["config_snapshot"] == cfg.config_snapshot


def test_decision_reproducible_from_stored_data(cfg, session):
    hist = _history(cfg)
    attrs = {"attr_diabetic": False, "attr_immunocompromised": False, "depth_type": "superficial"}
    result = rules.evaluate(hist, attrs, NOW, cfg, wound_id="wound-C")
    audit.persist_status(session, result, config_snapshot=cfg.config_snapshot)
    session.commit()

    stored = session.query(Status).filter_by(wound_id="wound-C").one()

    # Re-run the pure engine from the same inputs + the SAME config snapshot.
    cfg2 = load_config()
    assert cfg2.config_snapshot == stored.config_snapshot  # same config => same snapshot
    replay = rules.evaluate(hist, attrs, NOW, cfg2, wound_id="wound-C")

    assert replay.level == stored.level
    assert replay.machine_code == stored.machine_code
    assert replay.data_level == stored.data_level
    assert audit.status_to_factors(replay)["red_flags"] == stored.factors["red_flags"]


def test_persist_requires_wound_id(cfg, session):
    result = rules.evaluate(_history(cfg), {}, NOW, cfg)  # no wound_id
    with pytest.raises(ValueError):
        audit.persist_status(session, result)
