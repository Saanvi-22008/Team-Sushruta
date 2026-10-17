"""Staleness / sensor-health / confidence tests (FEAT-003).

Acceptance: stale data -> surfaced + reduced confidence; a disconnected sensor
is not a reassuring normal; simulated data is labelled; low battery + drift ->
reduced confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import load_config
from app.safety import rules
from app.safety import staleness as st

NOW = datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def clinical():
    cfg = load_config()
    assert cfg.loaded
    return cfg.clinical


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


def test_fresh_reading_not_stale_normal_confidence(clinical):
    hist = [FakeReading(ts=NOW - timedelta(seconds=30))]
    res = st.assess(hist, NOW, clinical)
    assert res.stale is False
    assert res.confidence == st.CONFIDENCE_NORMAL


def test_stale_data_surfaced_and_reduced_confidence(clinical):
    old = NOW - timedelta(seconds=clinical.freshness_window_s + 600)
    res = st.assess([FakeReading(ts=old)], NOW, clinical)
    assert res.stale is True
    assert res.confidence == st.CONFIDENCE_REDUCED
    assert res.latest_fresh is None


def test_stale_not_shown_as_fresh_normal_through_engine(clinical):
    # A stale but numerically-normal reading must NOT yield data_level 'normal'.
    old = NOW - timedelta(seconds=clinical.freshness_window_s + 600)
    out = rules.evaluate(
        [FakeReading(ts=old)],
        {"attr_diabetic": False, "attr_immunocompromised": False, "depth_type": "superficial"},
        NOW,
        clinical,
    )
    assert out.data_level == rules.DATA_LEVEL_UNKNOWN
    assert out.data_level != "normal"
    assert out.stale is True


def test_disconnected_sensor_not_reassuring_normal(clinical):
    hist = [FakeReading(ts=NOW - timedelta(seconds=30), sensor_status="disconnected")]
    res = st.assess(hist, NOW, clinical)
    assert res.sensor_health == "disconnected"
    assert res.confidence == st.CONFIDENCE_REDUCED


def test_drifting_sensor_reduces_confidence(clinical):
    hist = [FakeReading(ts=NOW - timedelta(seconds=30), sensor_status="drifting")]
    res = st.assess(hist, NOW, clinical)
    assert res.sensor_health == "drifting"
    assert res.confidence == st.CONFIDENCE_REDUCED


def test_simulated_data_labelled(clinical):
    hist = [FakeReading(ts=NOW - timedelta(seconds=30), simulated=True)]
    res = st.assess(hist, NOW, clinical)
    assert res.simulated is True
    out = rules.evaluate(
        hist,
        {"attr_diabetic": False, "attr_immunocompromised": False, "depth_type": "superficial"},
        NOW,
        clinical,
    )
    assert out.simulated is True


def test_low_battery_with_drift_reduces_confidence(clinical):
    low = clinical.low_battery_pct - 1
    hist = [
        FakeReading(ts=NOW - timedelta(seconds=30), battery_pct=low, sensor_status="drifting")
    ]
    res = st.assess(hist, NOW, clinical)
    assert res.confidence == st.CONFIDENCE_REDUCED
    assert any("battery" in r for r in res.reasons)


def test_low_battery_alone_without_drift_is_not_reduced(clinical):
    # Low battery but sensor ok and data fresh -> confidence stays normal
    # (reduced only when low battery coincides with drift, per Req 12.3).
    low = clinical.low_battery_pct - 1
    hist = [FakeReading(ts=NOW - timedelta(seconds=30), battery_pct=low, sensor_status="ok")]
    res = st.assess(hist, NOW, clinical)
    assert res.confidence == st.CONFIDENCE_NORMAL
