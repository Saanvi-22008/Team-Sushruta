"""The deterministic rules engine — the safety heart of the system.

``evaluate(history, attrs, now, config)`` is a PURE function (invariant #1):
config-only, no LLM/ML/network, no I/O, clock injected via ``now``; the same
inputs always produce the same :class:`StatusResult`.

Pipeline (design.md "Deterministic rules engine design"):

1. Select usable readings — a value flagged ``out_of_range``/``invalid_timestamp``
   is excluded from any computation that could LOWER status (invariant #3).
2. Derive ``data_level`` from the latest usable fresh reading + trends vs the
   config watch/infection-risk bands. No usable fresh reading =>
   ``data_level == 'unknown'``, NEVER ``'normal'`` (invariant #4).
3. Evaluate red flags; any present => candidate ``escalate`` (invariant #5).
4. Combine with ``max_severity`` so escalation only RAISES (invariant #2).
5. Compute confidence (stale / sensor drift-disconnect / low-battery+drift).
6. Build ``machine_code`` + plain-language ``reason`` naming the driving
   factor(s); escalate messaging always advises seeking care, never discourages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from app.core.config import ClinicalThresholds, SafetyConfig
from app.safety import red_flags as rf
from app.safety import staleness as st
from app.safety import trends as tr

# Level ordering: normal(0) < watch(1) < infection-risk(2) < escalate(3).
LEVEL_NORMAL = "normal"
LEVEL_WATCH = "watch"
LEVEL_INFECTION_RISK = "infection-risk"
LEVEL_ESCALATE = "escalate"

_LEVEL_ORDER = {
    LEVEL_NORMAL: 0,
    LEVEL_WATCH: 1,
    LEVEL_INFECTION_RISK: 2,
    LEVEL_ESCALATE: 3,
}

DATA_LEVEL_UNKNOWN = "unknown"


def level_severity(level: str) -> int:
    """Numeric severity of a *final* level (unknown is treated as watch-ish).

    ``unknown`` is not a reassuring result: for combination purposes it sits at
    least at ``watch`` so a lack of data never reads as ``normal``.
    """
    if level == DATA_LEVEL_UNKNOWN:
        return _LEVEL_ORDER[LEVEL_WATCH]
    return _LEVEL_ORDER.get(level, _LEVEL_ORDER[LEVEL_WATCH])


def max_severity(*levels: str) -> str:
    """Return the most-severe real level among ``levels`` (escalation only raises).

    ``unknown`` inputs are mapped to ``watch`` severity so they can never pull a
    result down to ``normal``; a true ``normal`` is only returned when every
    input is ``normal``.
    """
    best = LEVEL_NORMAL
    best_sev = _LEVEL_ORDER[LEVEL_NORMAL]
    for lvl in levels:
        sev = level_severity(lvl)
        if sev > best_sev:
            best_sev = sev
            # Map an unknown's severity back to a concrete reportable level.
            best = lvl if lvl in _LEVEL_ORDER else LEVEL_WATCH
    return best


@dataclass(frozen=True)
class StatusResult:
    """Immutable result of a deterministic evaluation.

    Fields map 1:1 onto the ``StatusOut`` wire schema (plus structured red-flag
    objects and factors for audit).
    """

    wound_id: Optional[str]
    level: str
    machine_code: str
    data_level: str
    red_flags: tuple[str, ...]
    sensor_health: str
    stale: bool
    simulated: bool
    trend: dict  # {"ph":..,"temp":..,"status":..}
    confidence: str
    reason: str
    last_updated: Optional[datetime]
    config_snapshot: Optional[str]
    factors: dict = field(default_factory=dict)
    red_flag_details: tuple[rf.RedFlag, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Data-driven level from the latest usable fresh reading + trends.
# ---------------------------------------------------------------------------
def _data_level(
    latest_fresh: Optional[Any],
    trend: tr.TrendResult,
    config: ClinicalThresholds,
) -> tuple[str, list[str]]:
    """Return (data_level, driving-factor codes).

    No usable fresh reading => ``unknown`` (never normal). Flagged metric values
    on the latest reading are excluded from any check that could LOWER status:
    an unusable metric simply does not contribute a reassuring normal, and when
    NO metric on the latest fresh reading is usable the level stays ``unknown``.
    """
    if latest_fresh is None:
        return DATA_LEVEL_UNKNOWN, ["no_usable_fresh_reading"]

    def usable(metric: str) -> bool:
        fn = getattr(latest_fresh, "has_usable", None)
        return fn(metric) if callable(fn) else True

    factors: list[str] = []
    level = LEVEL_NORMAL
    any_usable = False

    # pH band.
    if usable("ph"):
        any_usable = True
        ph = float(getattr(latest_fresh, "ph"))
        if ph > config.ph_infection_risk_above:
            level = max_severity(level, LEVEL_INFECTION_RISK)
            factors.append("ph_infection_risk")
        elif ph > config.ph_watch_above:
            level = max_severity(level, LEVEL_WATCH)
            factors.append("ph_watch")

    # Temperature band.
    if usable("skin_temp_c"):
        any_usable = True
        temp = float(getattr(latest_fresh, "skin_temp_c"))
        if temp > config.skin_temp_c_infection_risk_above:
            level = max_severity(level, LEVEL_INFECTION_RISK)
            factors.append("temp_infection_risk")
        elif temp > config.skin_temp_c_watch_above:
            level = max_severity(level, LEVEL_WATCH)
            factors.append("temp_watch")

    # Moisture watch band (watch only; no infection-risk band in config).
    if usable("moisture_pct"):
        any_usable = True
        moisture = float(getattr(latest_fresh, "moisture_pct"))
        if moisture > config.moisture_pct_watch_above:
            level = max_severity(level, LEVEL_WATCH)
            factors.append("moisture_watch")

    # Sustained rising trends raise the data-driven level too (not just normal).
    for metric, code in (("ph", "ph_trend_rising"), ("skin_temp_c", "temp_trend_rising")):
        mt = trend.for_metric(metric)
        if mt.ok and mt.sustained and mt.direction == tr.RISING:
            level = max_severity(level, LEVEL_WATCH)
            factors.append(code)

    # If the latest fresh reading had no usable metric at all, we cannot assert
    # a reassuring normal => unknown (invariant #4).
    if not any_usable:
        return DATA_LEVEL_UNKNOWN, ["no_usable_metric"]

    return level, factors


# ---------------------------------------------------------------------------
# Machine code + plain-language reason.
# ---------------------------------------------------------------------------
def _trend_word(mt: tr.MetricTrend) -> str:
    if not mt.ok:
        return tr.INSUFFICIENT_DATA
    return mt.direction


def _build_reason(
    level: str,
    data_level: str,
    data_factors: list[str],
    flags: list[rf.RedFlag],
    stale: bool,
    sensor_health: str,
) -> str:
    if level == LEVEL_ESCALATE and flags:
        names = ", ".join(f.label for f in flags)
        advice = " ".join(dict.fromkeys(f.advice for f in flags))  # dedupe, keep order
        return f"Escalate: {names}. {advice}"

    if data_level == DATA_LEVEL_UNKNOWN:
        bits = []
        if stale:
            bits.append("no fresh reading is available")
        if sensor_health != st.SENSOR_OK:
            bits.append(f"the sensor is {sensor_health}")
        detail = "; ".join(bits) if bits else "there is no usable recent reading"
        return (
            "Status is unknown because " + detail + ". This is not a clear 'all good'; "
            "please check the device and, if you are concerned, seek care."
        )

    if level == LEVEL_INFECTION_RISK:
        return (
            "Readings suggest a possible infection risk ("
            + _factor_phrase(data_factors)
            + "). Please monitor closely and consider contacting a doctor."
        )
    if level == LEVEL_WATCH:
        return (
            "Readings are worth watching ("
            + _factor_phrase(data_factors)
            + "). Keep an eye on the wound."
        )
    return "Readings are within normal ranges with no concerning trend or red flag."


_FACTOR_WORDS = {
    "ph_infection_risk": "pH high",
    "ph_watch": "pH slightly raised",
    "temp_infection_risk": "temperature high",
    "temp_watch": "temperature slightly raised",
    "moisture_watch": "high moisture",
    "ph_trend_rising": "pH rising over time",
    "temp_trend_rising": "temperature rising over time",
}


def _factor_phrase(factors: list[str]) -> str:
    words = [_FACTOR_WORDS.get(f, f) for f in factors]
    return ", ".join(words) if words else "trend"


def _machine_code(
    level: str, data_factors: list[str], flags: list[rf.RedFlag], data_level: str
) -> str:
    if level == LEVEL_ESCALATE and flags:
        return "ESCALATE_" + flags[0].code.removeprefix("RF_")
    if data_level == DATA_LEVEL_UNKNOWN:
        return "UNKNOWN_NO_USABLE_DATA"
    if level == LEVEL_INFECTION_RISK:
        key = data_factors[0] if data_factors else "trend"
        return "INFECTION_RISK_" + key.upper()
    if level == LEVEL_WATCH:
        key = data_factors[0] if data_factors else "trend"
        return "WATCH_" + key.upper()
    return "NORMAL"


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------
def _resolve_clinical(config: Any) -> ClinicalThresholds:
    """Accept either a SafetyConfig or a ClinicalThresholds; fail closed otherwise."""
    if isinstance(config, SafetyConfig):
        if not config.loaded or config.clinical is None:
            raise ValueError("safety config not loaded; cannot evaluate (fail-closed)")
        return config.clinical
    return config


def evaluate(
    history: Sequence[Any],
    attrs: Mapping[str, Any],
    now: datetime,
    config: Any,
    *,
    symptoms: Optional[Mapping[str, Any]] = None,
    config_snapshot: Optional[str] = None,
    wound_id: Optional[str] = None,
) -> StatusResult:
    """Deterministically evaluate wound status.

    Parameters
    ----------
    history:
        Sequence of reading-like objects (``ts``, metric attrs, ``has_usable``,
        ``sensor_status``, ``battery_pct``, ``simulated``). Need not be sorted.
    attrs:
        Wound attributes (``attr_diabetic``, ``attr_immunocompromised``,
        ``depth_type``, ...); missing/None == unknown (never assumed safe).
    now:
        Injected clock (the ONLY time source — nothing reads the wall clock).
    config:
        A :class:`SafetyConfig` (preferred) or a :class:`ClinicalThresholds`.
        A SafetyConfig that failed to load raises (fail-closed) rather than
        producing an unsafe default.
    symptoms:
        Mapping {kind: present}; missing == unknown.
    """
    clinical = _resolve_clinical(config)
    symptoms = symptoms or {}
    attrs = attrs or {}
    history = list(history or [])
    if config_snapshot is None and isinstance(config, SafetyConfig):
        config_snapshot = config.config_snapshot

    # 1 + freshness/sensor-health/confidence.
    stale_res = st.assess(history, now, clinical)

    # trends over the configured window.
    trend_res = tr.compute(history, now, clinical.trend_window_s)

    # 2. Data-driven level from the latest usable FRESH reading. A stale wound
    #    has no fresh reading => unknown (never normal).
    latest_fresh = stale_res.latest_fresh
    data_level, data_factors = _data_level(latest_fresh, trend_res, clinical)

    # 3. Red flags.
    flags = rf.evaluate(
        attrs, symptoms, trend_res, clinical, history=history, now=now
    )

    # 4. Combine — escalation only raises; unknown never reads as normal.
    candidate = data_level
    if flags:
        candidate = max_severity(candidate, LEVEL_ESCALATE)
    final_level = max_severity(candidate)
    # Preserve a genuine "unknown" label on the data component while reporting a
    # concrete level: when data is unknown and no red flag, surface watch-level
    # caution (never normal) but keep data_level == unknown for the UI.
    if not flags and data_level == DATA_LEVEL_UNKNOWN:
        final_level = LEVEL_WATCH

    # 5. Confidence already computed in stale_res.
    confidence = stale_res.confidence

    # 6. Explain.
    machine_code = _machine_code(final_level, data_factors, flags, data_level)
    reason = _build_reason(
        final_level, data_level, data_factors, flags, stale_res.stale, stale_res.sensor_health
    )

    last_updated = getattr(stale_res.latest, "ts", None) if stale_res.latest else None

    trend_dict = {
        "ph": _trend_word(trend_res.ph),
        "temp": _trend_word(trend_res.skin_temp_c),
        "status": trend_res.status,
    }

    factors = {
        "data_level": data_level,
        "data_factors": data_factors,
        "red_flags": [f.code for f in flags],
        "red_flags_from_unknown": [f.code for f in flags if f.from_unknown],
        "stale": stale_res.stale,
        "sensor_health": stale_res.sensor_health,
        "confidence": confidence,
        "trend": trend_dict,
    }

    return StatusResult(
        wound_id=wound_id,
        level=final_level,
        machine_code=machine_code,
        data_level=data_level,
        red_flags=tuple(f.code for f in flags),
        sensor_health=stale_res.sensor_health,
        stale=stale_res.stale,
        simulated=stale_res.simulated,
        trend=trend_dict,
        confidence=confidence,
        reason=reason,
        last_updated=last_updated,
        config_snapshot=config_snapshot,
        factors=factors,
        red_flag_details=tuple(flags),
    )
