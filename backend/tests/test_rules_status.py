"""Rules-engine status tests (FEAT-003).

Acceptance: normal/watch/infection-risk cases derived from config; most-severe
combination wins; a flagged value cannot LOWER status; no usable fresh data ->
data_level 'unknown' (not normal); identical input -> identical output (pure).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import load_config
from app.safety import rules

NOW = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# Attributes that are explicitly known-safe so unknown-conservative red flags
# don't fire in the data-driven level tests.
_SAFE_ATTRS = {
    "attr_diabetic": False,
    "attr_immunocompromised": False,
    "depth_type": "superficial",
}


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
    flags: dict = None

    def has_usable(self, metric: str) -> bool:
        if not self.flags:
            return True
        return self.flags.get(metric, "ok") == "ok"


def _fresh(ph=7.0, temp=32.0, moisture=45.0, **kw):
    return FakeReading(ts=NOW - timedelta(seconds=30), ph=ph, skin_temp_c=temp,
                       moisture_pct=moisture, **kw)


# -- data-driven levels from config ---------------------------------------


def test_normal_within_ranges(clinical):
    res = rules.evaluate([_fresh()], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.LEVEL_NORMAL
    assert res.level == rules.LEVEL_NORMAL
    assert res.red_flags == ()


def test_watch_from_ph_watch_band(clinical):
    ph = clinical.ph_watch_above + 0.1  # above watch, below infection-risk
    res = rules.evaluate([_fresh(ph=ph)], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.LEVEL_WATCH
    assert res.level == rules.LEVEL_WATCH


def test_infection_risk_from_ph_band(clinical):
    ph = clinical.ph_infection_risk_above + 0.1
    res = rules.evaluate([_fresh(ph=ph)], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.LEVEL_INFECTION_RISK
    assert res.level == rules.LEVEL_INFECTION_RISK


def test_infection_risk_from_temp_band(clinical):
    temp = clinical.skin_temp_c_infection_risk_above + 0.1
    res = rules.evaluate([_fresh(temp=temp)], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.LEVEL_INFECTION_RISK


def test_moisture_watch_band(clinical):
    moisture = clinical.moisture_pct_watch_above + 1
    res = rules.evaluate([_fresh(moisture=moisture)], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.LEVEL_WATCH


# -- most-severe combination wins -----------------------------------------


def test_most_severe_wins(clinical):
    # pH only watch, temp infection-risk -> overall infection-risk.
    ph = clinical.ph_watch_above + 0.1
    temp = clinical.skin_temp_c_infection_risk_above + 0.1
    res = rules.evaluate([_fresh(ph=ph, temp=temp)], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.LEVEL_INFECTION_RISK


def test_red_flag_forces_escalate_over_normal_data(clinical):
    attrs = dict(_SAFE_ATTRS, attr_diabetic=True)
    res = rules.evaluate([_fresh()], attrs, NOW, clinical)
    assert res.level == rules.LEVEL_ESCALATE
    assert res.data_level == rules.LEVEL_NORMAL  # data component unchanged


def test_max_severity_helper():
    assert rules.max_severity("normal", "watch") == "watch"
    assert rules.max_severity("watch", "infection-risk") == "infection-risk"
    assert rules.max_severity("infection-risk", "escalate") == "escalate"
    # escalation only raises: a lower level never pulls it down
    assert rules.max_severity("escalate", "normal") == "escalate"
    # unknown never reads as normal
    assert rules.max_severity("unknown", "normal") == "watch"


# -- a flagged value cannot LOWER status ----------------------------------


def test_flagged_value_cannot_lower_status(clinical):
    # Latest fresh reading: temp genuinely infection-risk, but pH reads a
    # falsely-low 'normal' value that is FLAGGED out_of_range. The flagged pH
    # must be ignored so it cannot drag the status down to normal.
    temp = clinical.skin_temp_c_infection_risk_above + 0.5
    r = _fresh(ph=7.0, temp=temp)
    r.flags = {"ph": "out_of_range"}
    res = rules.evaluate([r], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.LEVEL_INFECTION_RISK


def test_all_metrics_flagged_yields_unknown(clinical):
    r = _fresh()
    r.flags = {
        "ph": "out_of_range",
        "skin_temp_c": "out_of_range",
        "moisture_pct": "invalid_timestamp",
    }
    res = rules.evaluate([r], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.DATA_LEVEL_UNKNOWN


# -- no usable fresh data -> unknown (not normal) -------------------------


def test_no_readings_data_level_unknown(clinical):
    res = rules.evaluate([], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.DATA_LEVEL_UNKNOWN
    assert res.data_level != "normal"


def test_stale_only_data_level_unknown(clinical):
    stale = FakeReading(ts=NOW - timedelta(seconds=clinical.freshness_window_s + 100))
    res = rules.evaluate([stale], _SAFE_ATTRS, NOW, clinical)
    assert res.data_level == rules.DATA_LEVEL_UNKNOWN


def test_unknown_data_level_reports_cautious_level_not_normal(clinical):
    res = rules.evaluate([], _SAFE_ATTRS, NOW, clinical)
    assert res.level != rules.LEVEL_NORMAL  # never a reassuring normal


# -- purity / determinism --------------------------------------------------


def test_identical_input_identical_output(clinical):
    attrs = dict(_SAFE_ATTRS)
    hist = [_fresh(ph=clinical.ph_watch_above + 0.1)]
    r1 = rules.evaluate(hist, attrs, NOW, clinical)
    r2 = rules.evaluate(hist, attrs, NOW, clinical)
    assert r1 == r2


def test_result_has_full_status_shape(clinical):
    res = rules.evaluate([_fresh()], _SAFE_ATTRS, NOW, clinical)
    for attrname in (
        "wound_id", "level", "machine_code", "data_level", "red_flags",
        "sensor_health", "stale", "simulated", "trend", "confidence", "reason",
    ):
        assert hasattr(res, attrname)
    assert set(res.trend) == {"ph", "temp", "status"}


def test_safety_modules_have_no_network_or_ml_imports():
    # Invariant: nothing under app.safety imports a network/LLM/ML library.
    import pathlib

    import app.safety as pkg

    banned = ("requests", "httpx", "urllib", "socket", "openai", "torch",
              "tensorflow", "sklearn", "numpy.random", "boto3")
    root = pathlib.Path(pkg.__file__).parent
    for py in root.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for mod in banned:
            assert f"import {mod}" not in text, f"{py.name} imports {mod}"
