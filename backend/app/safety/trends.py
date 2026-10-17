"""Trend-window computation (pure, deterministic).

``compute(history, now, window_s)`` looks back over the configured trend window
and reports, per metric, a direction (``rising`` | ``falling`` | ``steady``)
plus a signed magnitude, OR ``insufficient_data`` when too few usable points
fall inside the window.

SAFETY NOTES
------------
- Only values that are *usable* (``field_flags[metric] == 'ok'``) contribute to
  a trend. A value flagged ``out_of_range``/``invalid_timestamp`` is excluded so
  it can never fabricate a reassuring (status-lowering) trend (invariant #3).
- Too few usable points in the window => ``insufficient_data`` for that metric,
  never a false "steady / all-clear" (Req 7.3 / invariant #4).
- A single spike is not a sustained trend: direction is judged from the first
  vs last usable point in the window (net change), so one outlier between them
  does not flip a steady metric. ``sustained`` is only true when the net
  magnitude clears a threshold AND there are enough points to see a direction.
- Deterministic: identical history + identical ``now``/``window`` => identical
  result (no clock read, no RNG, stable ordering by ``ts``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

# Trend direction / status constants.
RISING = "rising"
FALLING = "falling"
STEADY = "steady"
INSUFFICIENT_DATA = "insufficient_data"

# Minimum usable points inside the window needed to judge a direction at all.
MIN_POINTS = 3

# Per-metric net change (last - first) that counts as a *sustained* move.
# These are trend-shape sensitivities, not clinical thresholds (those live in
# config and are applied by rules.py); keeping them here avoids a false trend
# from ordinary sensor noise.
_SUSTAINED_DELTA = {
    "ph": 0.3,
    "skin_temp_c": 1.0,
    "moisture_pct": 10.0,
}

_METRICS = ("ph", "skin_temp_c", "moisture_pct")


@dataclass(frozen=True)
class MetricTrend:
    """Trend of one metric across the window."""

    metric: str
    status: str  # ok | insufficient_data
    direction: str  # rising | falling | steady (meaningful only when status==ok)
    magnitude: float  # signed net change (last - first); 0.0 when insufficient
    sustained: bool  # True only for an ok, sufficiently-large, directional move
    n_points: int

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class TrendResult:
    """Trends for every metric plus an overall computation status."""

    ph: MetricTrend
    skin_temp_c: MetricTrend
    moisture_pct: MetricTrend
    status: str  # ok if ANY metric computed; insufficient_data if none could

    def for_metric(self, metric: str) -> MetricTrend:
        return getattr(self, metric)


def _usable_points(
    history: Sequence[Any], metric: str, now: datetime, window_s: int
) -> list[tuple[datetime, float]]:
    """Return (ts, value) pairs for ``metric`` that are usable and in-window.

    A point is kept only when its ``metric`` flag is usable (not out_of_range /
    invalid_timestamp) and its ts falls within ``[now - window, now]``. Points
    are returned sorted by ts so the result is independent of input ordering.
    """
    cutoff = now - timedelta(seconds=window_s)
    points: list[tuple[datetime, float]] = []
    for r in history:
        ts = getattr(r, "ts", None)
        if ts is None:
            continue
        # Honor explicit usability gating when the reading exposes it.
        has_usable = getattr(r, "has_usable", None)
        if callable(has_usable) and not has_usable(metric):
            continue
        if ts < cutoff or ts > now:
            continue
        value = getattr(r, metric, None)
        if value is None:
            continue
        points.append((ts, float(value)))
    points.sort(key=lambda p: p[0])
    return points


def _compute_metric(
    history: Sequence[Any], metric: str, now: datetime, window_s: int
) -> MetricTrend:
    points = _usable_points(history, metric, now, window_s)
    n = len(points)
    if n < MIN_POINTS:
        return MetricTrend(
            metric=metric,
            status=INSUFFICIENT_DATA,
            direction=STEADY,
            magnitude=0.0,
            sustained=False,
            n_points=n,
        )

    first_val = points[0][1]
    last_val = points[-1][1]
    magnitude = last_val - first_val
    threshold = _SUSTAINED_DELTA.get(metric, 0.0)

    if magnitude >= threshold:
        direction = RISING
        sustained = True
    elif magnitude <= -threshold:
        direction = FALLING
        sustained = True
    else:
        direction = STEADY
        sustained = False

    return MetricTrend(
        metric=metric,
        status="ok",
        direction=direction,
        magnitude=round(magnitude, 6),
        sustained=sustained,
        n_points=n,
    )


def compute(history: Sequence[Any], now: datetime, window_s: int) -> TrendResult:
    """Compute per-metric trends over ``window_s`` ending at ``now``.

    Pure and deterministic. ``history`` is any sequence of reading-like objects
    exposing ``ts`` and the metric attributes (and, optionally, ``has_usable``);
    it need not be pre-sorted.
    """
    ph = _compute_metric(history, "ph", now, window_s)
    temp = _compute_metric(history, "skin_temp_c", now, window_s)
    moisture = _compute_metric(history, "moisture_pct", now, window_s)
    overall = "ok" if any(m.status == "ok" for m in (ph, temp, moisture)) else INSUFFICIENT_DATA
    return TrendResult(ph=ph, skin_temp_c=temp, moisture_pct=moisture, status=overall)
