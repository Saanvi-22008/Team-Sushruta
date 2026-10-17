"""Trend-window tests (FEAT-003).

Acceptance: sustained rise detected; a single spike is NOT sustained; too few
points -> insufficient_data; identical history -> identical result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.core.config import load_config
from app.safety import trends as tr

NOW = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def clinical():
    cfg = load_config()
    assert cfg.loaded, f"config failed to load: {cfg.load_error}"
    return cfg.clinical


@dataclass
class FakeReading:
    """Minimal reading-like object the trend code duck-types on."""

    ts: datetime
    ph: float = 7.0
    skin_temp_c: float = 32.0
    moisture_pct: float = 45.0
    flags: Optional[dict] = None

    def has_usable(self, metric: str) -> bool:
        if not self.flags:
            return True
        return self.flags.get(metric, "ok") == "ok"


def _history(window_s: int, values, metric="ph", spacing_frac=0.1):
    """Build a history spread evenly inside ``window_s`` ending just before NOW."""
    out = []
    n = len(values)
    for i, v in enumerate(values):
        # values[0] is the OLDEST (furthest back in time), values[-1] newest.
        offset = window_s * (1 - spacing_frac * i)
        ts = NOW - timedelta(seconds=max(1, offset))
        kwargs = {metric: v}
        out.append(FakeReading(ts=ts, **kwargs))
    return out


def test_sustained_rise_detected(clinical):
    hist = _history(clinical.trend_window_s, [7.0, 7.3, 7.6, 7.9, 8.2], metric="ph")
    res = tr.compute(hist, NOW, clinical.trend_window_s)
    mt = res.ph
    assert mt.ok
    assert mt.direction == tr.RISING
    assert mt.sustained is True
    assert mt.magnitude > 0


def test_single_spike_not_sustained(clinical):
    # Flat except one spike in the middle; net change (first vs last) ~ 0.
    hist = _history(clinical.trend_window_s, [7.0, 7.0, 9.0, 7.0, 7.0], metric="ph")
    res = tr.compute(hist, NOW, clinical.trend_window_s)
    mt = res.ph
    assert mt.ok
    assert mt.sustained is False
    assert mt.direction == tr.STEADY


def test_too_few_points_insufficient_data(clinical):
    hist = _history(clinical.trend_window_s, [7.0, 7.5], metric="ph")  # 2 < MIN_POINTS
    res = tr.compute(hist, NOW, clinical.trend_window_s)
    assert res.ph.status == tr.INSUFFICIENT_DATA
    assert res.ph.sustained is False


def test_points_outside_window_excluded(clinical):
    # One usable in-window point + two way outside the window -> insufficient.
    inside = FakeReading(ts=NOW - timedelta(seconds=10), ph=7.5)
    old1 = FakeReading(ts=NOW - timedelta(seconds=clinical.trend_window_s * 5), ph=7.0)
    old2 = FakeReading(ts=NOW - timedelta(seconds=clinical.trend_window_s * 6), ph=7.1)
    res = tr.compute([inside, old1, old2], NOW, clinical.trend_window_s)
    assert res.ph.status == tr.INSUFFICIENT_DATA


def test_flagged_values_excluded_from_trend(clinical):
    # Three points but the two needed to clear MIN_POINTS are flagged unusable.
    pts = _history(clinical.trend_window_s, [7.0, 7.5, 8.0], metric="ph")
    pts[1].flags = {"ph": "out_of_range"}
    pts[2].flags = {"ph": "invalid_timestamp"}
    res = tr.compute(pts, NOW, clinical.trend_window_s)
    assert res.ph.status == tr.INSUFFICIENT_DATA


def test_identical_history_identical_result(clinical):
    hist1 = _history(clinical.trend_window_s, [7.0, 7.3, 7.6, 7.9], metric="ph")
    hist2 = _history(clinical.trend_window_s, [7.0, 7.3, 7.6, 7.9], metric="ph")
    r1 = tr.compute(hist1, NOW, clinical.trend_window_s)
    r2 = tr.compute(hist2, NOW, clinical.trend_window_s)
    assert r1 == r2


def test_input_order_does_not_change_result(clinical):
    hist = _history(clinical.trend_window_s, [7.0, 7.3, 7.6, 7.9], metric="ph")
    reordered = list(reversed(hist))
    assert tr.compute(hist, NOW, clinical.trend_window_s) == tr.compute(
        reordered, NOW, clinical.trend_window_s
    )
