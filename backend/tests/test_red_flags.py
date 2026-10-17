"""Red-flag tests (FEAT-003).

One dedicated test PER red-flag rule. Each asserts (a) the rule fires in
isolation and (b) through the engine it forces the final status to ``escalate``
with care-seeking (never discouraging) messaging. Plus: an unknown relevant
attribute is NOT downgraded to the safe value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.core.config import load_config
from app.safety import red_flags as rf
from app.safety import rules
from app.safety import trends as tr

NOW = datetime(2026, 1, 10, 0, 0, 0, tzinfo=timezone.utc)

# Phrases that would DISCOURAGE seeking care — must never appear in advice.
_DISCOURAGING = [
    "no need to see",
    "don't see a doctor",
    "do not see a doctor",
    "no need for care",
    "ignore",
    "not necessary to seek",
]


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


def _fresh_normal_history():
    """A short, fresh, perfectly-normal history (would be 'normal' on its own)."""
    return [FakeReading(ts=NOW - timedelta(seconds=60 * i)) for i in range(3)]


def _assert_care_seeking(flag: rf.RedFlag):
    low = flag.advice.lower()
    for bad in _DISCOURAGING:
        assert bad not in low, f"advice discourages care: {flag.advice!r}"
    assert any(w in low for w in ("care", "doctor", "medical")), flag.advice


def _escalates(clinical, *, attrs=None, symptoms=None, history=None, expect_code):
    res = rules.evaluate(
        history if history is not None else _fresh_normal_history(),
        attrs or {},
        NOW,
        clinical,
        symptoms=symptoms or {},
    )
    assert res.level == rules.LEVEL_ESCALATE, res.level
    assert expect_code in res.red_flags, (expect_code, res.red_flags)
    # Reason names a flag and advises care.
    low = res.reason.lower()
    assert any(w in low for w in ("care", "doctor", "medical"))
    for bad in _DISCOURAGING:
        assert bad not in low
    return res


# -- one test per rule -----------------------------------------------------


def test_spreading_redness(clinical):
    flag = rf.check_spreading_redness({"spreading_redness": True})
    assert flag and flag.code == rf.RF_SPREADING_REDNESS
    _assert_care_seeking(flag)
    _escalates(clinical, symptoms={"spreading_redness": True}, expect_code=rf.RF_SPREADING_REDNESS)


def test_pus(clinical):
    flag = rf.check_pus({"pus": True})
    assert flag and flag.code == rf.RF_PUS
    _assert_care_seeking(flag)
    _escalates(clinical, symptoms={"pus": True}, expect_code=rf.RF_PUS)


def test_fever(clinical):
    flag = rf.check_fever({"fever": True})
    assert flag and flag.code == rf.RF_FEVER
    _assert_care_seeking(flag)
    _escalates(clinical, symptoms={"fever": True}, expect_code=rf.RF_FEVER)


def test_severe_pain(clinical):
    flag = rf.check_severe_pain({"severe_pain": True})
    assert flag and flag.code == rf.RF_SEVERE_PAIN
    _assert_care_seeking(flag)
    _escalates(clinical, symptoms={"severe_pain": True}, expect_code=rf.RF_SEVERE_PAIN)


def test_rapid_worsening_symptom(clinical):
    flag = rf.check_rapid_worsening({"rapid_worsening": True}, None)
    assert flag and flag.code == rf.RF_RAPID_WORSENING
    _assert_care_seeking(flag)
    _escalates(clinical, symptoms={"rapid_worsening": True}, expect_code=rf.RF_RAPID_WORSENING)


def test_deep_wound(clinical):
    flag = rf.check_deep_wound({"depth_type": "deep"}, clinical)
    assert flag and flag.code == rf.RF_DEEP_WOUND
    _assert_care_seeking(flag)
    _escalates(clinical, attrs={"depth_type": "deep", "attr_diabetic": False,
                                "attr_immunocompromised": False},
               expect_code=rf.RF_DEEP_WOUND)


def test_bite_puncture(clinical):
    flag = rf.check_bite_puncture({"depth_type": "puncture"}, {})
    assert flag and flag.code == rf.RF_BITE_PUNCTURE
    _assert_care_seeking(flag)
    _escalates(clinical, attrs={"depth_type": "puncture", "attr_diabetic": False,
                                "attr_immunocompromised": False},
               expect_code=rf.RF_BITE_PUNCTURE)


def test_diabetic(clinical):
    flag = rf.check_diabetic({"attr_diabetic": True}, clinical)
    assert flag and flag.code == rf.RF_DIABETIC
    _assert_care_seeking(flag)
    _escalates(clinical, attrs={"attr_diabetic": True, "attr_immunocompromised": False,
                                "depth_type": "superficial"},
               expect_code=rf.RF_DIABETIC)


def test_immunocompromised(clinical):
    flag = rf.check_immunocompromised({"attr_immunocompromised": True}, clinical)
    assert flag and flag.code == rf.RF_IMMUNOCOMPROMISED
    _assert_care_seeking(flag)
    _escalates(clinical, attrs={"attr_immunocompromised": True, "attr_diabetic": False,
                                "depth_type": "superficial"},
               expect_code=rf.RF_IMMUNOCOMPROMISED)


def test_no_improvement_over_n_days(clinical):
    n = clinical.no_improvement_days
    # History spanning > N days, pH flat/not improving.
    hist = [
        FakeReading(ts=NOW - timedelta(days=n + 2), ph=7.7),
        FakeReading(ts=NOW - timedelta(days=n), ph=7.7),
        FakeReading(ts=NOW - timedelta(hours=2), ph=7.7),
    ]
    trend = tr.compute(hist, NOW, clinical.trend_window_s)
    flag = rf.check_no_improvement(hist, NOW, clinical, trend)
    assert flag and flag.code == rf.RF_NO_IMPROVEMENT
    _assert_care_seeking(flag)
    _escalates(clinical, attrs={"attr_diabetic": False, "attr_immunocompromised": False,
                                "depth_type": "superficial"},
               history=hist, expect_code=rf.RF_NO_IMPROVEMENT)


def test_sustained_abnormal_trend(clinical):
    # Sustained rising pH across the window.
    w = clinical.trend_window_s
    hist = [
        FakeReading(ts=NOW - timedelta(seconds=int(w * 0.9)), ph=7.0),
        FakeReading(ts=NOW - timedelta(seconds=int(w * 0.5)), ph=7.4),
        FakeReading(ts=NOW - timedelta(seconds=int(w * 0.1)), ph=7.9),
    ]
    trend = tr.compute(hist, NOW, w)
    flag = rf.check_sustained_abnormal_trend(trend)
    assert flag and flag.code == rf.RF_SUSTAINED_ABNORMAL_TREND
    _assert_care_seeking(flag)
    _escalates(clinical, attrs={"attr_diabetic": False, "attr_immunocompromised": False,
                                "depth_type": "superficial"},
               history=hist, expect_code=rf.RF_SUSTAINED_ABNORMAL_TREND)


# -- unknown attributes are NOT downgraded to safe -------------------------


def test_unknown_diabetic_not_treated_as_safe(clinical):
    # attr_diabetic missing/None == unknown; conservative policy must flag it,
    # never silently assume non-diabetic (safe).
    flag = rf.check_diabetic({"attr_diabetic": None}, clinical)
    assert flag is not None
    assert flag.code == rf.RF_DIABETIC
    assert flag.from_unknown is True
    _assert_care_seeking(flag)


def test_unknown_immunocompromised_not_treated_as_safe(clinical):
    flag = rf.check_immunocompromised({}, clinical)  # key missing == unknown
    assert flag is not None
    assert flag.from_unknown is True


def test_unknown_depth_not_treated_as_safe(clinical):
    flag = rf.check_deep_wound({"depth_type": None}, clinical)
    assert flag is not None
    assert flag.from_unknown is True


def test_unknown_attrs_force_escalate_through_engine(clinical):
    # A perfectly normal, fresh reading but ALL risk attributes unknown.
    res = rules.evaluate(_fresh_normal_history(), {}, NOW, clinical, symptoms={})
    assert res.level == rules.LEVEL_ESCALATE
    # The unknowns are surfaced, not assumed safe.
    assert res.factors["red_flags_from_unknown"]


def test_explicit_false_attr_is_not_a_flag(clinical):
    # When explicitly known-false, no unknown-based flag should fire.
    assert rf.check_diabetic({"attr_diabetic": False}, clinical) is None
    assert rf.check_immunocompromised({"attr_immunocompromised": False}, clinical) is None
