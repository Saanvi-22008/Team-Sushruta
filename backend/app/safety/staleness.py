"""Freshness, sensor-health, and confidence (pure, deterministic).

``assess(history, now, config)`` reports:

- ``stale``        — True when there is no usable reading inside
  ``config.freshness_window_s`` ending at ``now``. Stale data is NEVER
  presented as a fresh normal (invariant #10); the rules engine turns a stale
  state into ``data_level == 'unknown'``.
- ``sensor_health``— the ``sensor_status`` of the latest reading
  (``ok`` | ``drifting`` | ``disconnected``), passed through unchanged. A
  ``disconnected`` sensor is surfaced, not smoothed into a reassuring normal.
- ``confidence``   — ``reduced`` when the data is stale, OR the sensor is
  ``drifting``/``disconnected``, OR a low battery
  (``battery_pct < config.low_battery_pct``) coincides with drift
  (Req 8.3 / 12.3). Otherwise ``normal``.
- ``simulated``    — True if any usable in-window reading is simulated, so the
  caller can label it SIMULATED.

The clock is injected via ``now``; no module here reads the wall clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence

from app.core.config import ClinicalThresholds

CONFIDENCE_NORMAL = "normal"
CONFIDENCE_REDUCED = "reduced"

SENSOR_OK = "ok"
SENSOR_DRIFTING = "drifting"
SENSOR_DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class StalenessResult:
    """Freshness + sensor-health + confidence summary."""

    stale: bool
    sensor_health: str
    confidence: str
    simulated: bool
    latest: Optional[Any] = None  # latest reading by ts (any usability), or None
    latest_fresh: Optional[Any] = None  # latest reading inside the freshness window
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _latest_by_ts(history: Sequence[Any]) -> Optional[Any]:
    best = None
    best_ts: Optional[datetime] = None
    for r in history:
        ts = getattr(r, "ts", None)
        if ts is None:
            continue
        if best_ts is None or ts > best_ts:
            best_ts = ts
            best = r
    return best


def _fresh_readings(
    history: Sequence[Any], now: datetime, window_s: int
) -> list[Any]:
    cutoff = now - timedelta(seconds=window_s)
    out = []
    for r in history:
        ts = getattr(r, "ts", None)
        if ts is None:
            continue
        if cutoff <= ts <= now:
            out.append(r)
    out.sort(key=lambda r: getattr(r, "ts"))
    return out


def assess(
    history: Sequence[Any], now: datetime, config: ClinicalThresholds
) -> StalenessResult:
    """Compute freshness/sensor-health/confidence for ``history`` as of ``now``."""
    history = list(history or [])
    latest = _latest_by_ts(history)
    fresh = _fresh_readings(history, now, config.freshness_window_s)
    latest_fresh = fresh[-1] if fresh else None

    stale = latest_fresh is None
    reasons: list[str] = []
    if stale:
        reasons.append("no fresh reading within the freshness window")

    # Sensor health is read from the latest reading overall (so a disconnected
    # sensor is surfaced even when the data is stale).
    sensor_health = SENSOR_OK
    if latest is not None:
        sensor_health = str(getattr(latest, "sensor_status", SENSOR_OK))

    # Simulated if any fresh reading is simulated (fall back to latest overall
    # when stale) — simulated data must never be shown as live.
    simulated = any(bool(getattr(r, "simulated", False)) for r in fresh)
    if not fresh and latest is not None:
        simulated = bool(getattr(latest, "simulated", False))

    confidence = CONFIDENCE_NORMAL
    if stale:
        confidence = CONFIDENCE_REDUCED
    if sensor_health in (SENSOR_DRIFTING, SENSOR_DISCONNECTED):
        confidence = CONFIDENCE_REDUCED
        reasons.append(f"sensor {sensor_health}")

    # Low battery coinciding with drift reduces confidence (Req 12.3).
    if latest is not None:
        battery = getattr(latest, "battery_pct", None)
        if (
            battery is not None
            and float(battery) < config.low_battery_pct
            and sensor_health in (SENSOR_DRIFTING, SENSOR_DISCONNECTED)
        ):
            confidence = CONFIDENCE_REDUCED
            reasons.append("low battery with sensor drift")

    return StalenessResult(
        stale=stale,
        sensor_health=sensor_health,
        confidence=confidence,
        simulated=simulated,
        latest=latest,
        latest_fresh=latest_fresh,
        reasons=tuple(reasons),
    )
