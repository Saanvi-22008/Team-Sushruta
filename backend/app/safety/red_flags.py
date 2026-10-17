"""Red-flag rules (pure, deterministic, config-driven).

A *red flag* is any condition that forces the status to ``escalate`` regardless
of how reassuring the numbers look (Req 6.2 / invariant #5). Each rule is a
small, independently callable function returning a :class:`RedFlag` or ``None``,
so every rule has its own unit test and can be reasoned about in isolation.

The twelve rules (Req 6.1):

1.  spreading redness   (symptom)
2.  pus                 (symptom)
3.  fever               (symptom)
4.  severe pain         (symptom)
5.  rapid worsening     (symptom OR a steep sustained abnormal trend)
6.  deep/gaping wound   (wound attribute)
7.  bite/puncture wound (wound attribute / symptom)
8.  diabetic user       (wound attribute)
9.  immunocompromised   (wound attribute)
10. no improvement over N days (history span with no sustained improvement; N from config)
11. sustained abnormal trend   (trend crossing an abnormal direction over the window)

UNKNOWN HANDLING (Req 6.4 / invariant #5):
When an attribute relevant to a red flag is ``unknown`` (``None`` /
missing / not provided), the rule MUST NOT treat it as the safe value. Under
``config.unknown_attr_policy == 'conservative'`` an unknown risk attribute (for
example diabetic/immunocompromised) raises a red flag that *surfaces the missing
input* and forces escalate. It is never silently downgraded to "safe".

Every red flag carries a care-seeking ``advice`` string: it always advises
seeking care and NEVER discourages it (Req 6.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from app.core.config import ClinicalThresholds
from app.safety import trends as trends_mod

# ---------------------------------------------------------------------------
# Red-flag codes (stable machine identifiers).
# ---------------------------------------------------------------------------
RF_SPREADING_REDNESS = "RF_SPREADING_REDNESS"
RF_PUS = "RF_PUS"
RF_FEVER = "RF_FEVER"
RF_SEVERE_PAIN = "RF_SEVERE_PAIN"
RF_RAPID_WORSENING = "RF_RAPID_WORSENING"
RF_DEEP_WOUND = "RF_DEEP_WOUND"
RF_BITE_PUNCTURE = "RF_BITE_PUNCTURE"
RF_DIABETIC = "RF_DIABETIC"
RF_IMMUNOCOMPROMISED = "RF_IMMUNOCOMPROMISED"
RF_NO_IMPROVEMENT = "RF_NO_IMPROVEMENT"
RF_SUSTAINED_ABNORMAL_TREND = "RF_SUSTAINED_ABNORMAL_TREND"

# Shared care-seeking phrasing. These advise seeking care and never discourage.
_CARE = "Please contact a doctor or seek medical care."
_CARE_SOON = "Please seek medical care promptly."

# A conservative unknown is flagged (not downgraded) with this suffix so the UI
# can surface that an input is missing rather than assumed safe.
_UNKNOWN_SUFFIX = " This information is missing, so it is treated conservatively; please confirm with a clinician."


@dataclass(frozen=True)
class RedFlag:
    """One active red flag.

    ``code`` is the stable machine identifier; ``label`` is a short human name;
    ``advice`` is care-seeking guidance that NEVER discourages seeking care;
    ``from_unknown`` marks a flag raised because a relevant attribute was
    unknown (surfaced, not assumed safe).
    """

    code: str
    label: str
    advice: str
    from_unknown: bool = False


# ---------------------------------------------------------------------------
# Symptom helpers.
#
# ``symptoms`` is a mapping {kind: present}. A value of True means the symptom is
# reported present; False means explicitly reported absent; a missing key means
# *unknown* (not reported). Symptom red flags fire ONLY on an explicit True —
# we never invent a symptom — but we also never treat a missing symptom as a
# reason to lower status (symptoms can only add escalation, never remove it).
# ---------------------------------------------------------------------------
def _symptom_present(symptoms: Mapping[str, Any], kind: str) -> bool:
    return bool(symptoms.get(kind) is True)


# ---------------------------------------------------------------------------
# Attribute helpers. ``attrs`` is a mapping; a missing key or None == unknown.
# ---------------------------------------------------------------------------
def _is_conservative(config: ClinicalThresholds) -> bool:
    return getattr(config, "unknown_attr_policy", "conservative") == "conservative"


def _attr(attrs: Mapping[str, Any], key: str) -> Optional[Any]:
    return attrs.get(key)


# ===========================================================================
# Individual rules. Each returns a RedFlag or None and is independently tested.
# ===========================================================================
def check_spreading_redness(symptoms: Mapping[str, Any]) -> Optional[RedFlag]:
    if _symptom_present(symptoms, "spreading_redness"):
        return RedFlag(
            RF_SPREADING_REDNESS,
            "spreading redness",
            "Spreading redness can signal infection. " + _CARE_SOON,
        )
    return None


def check_pus(symptoms: Mapping[str, Any]) -> Optional[RedFlag]:
    if _symptom_present(symptoms, "pus"):
        return RedFlag(
            RF_PUS,
            "pus / discharge",
            "Pus or discharge can signal infection. " + _CARE_SOON,
        )
    return None


def check_fever(symptoms: Mapping[str, Any]) -> Optional[RedFlag]:
    if _symptom_present(symptoms, "fever"):
        return RedFlag(
            RF_FEVER,
            "fever",
            "Fever alongside a wound can signal infection. " + _CARE_SOON,
        )
    return None


def check_severe_pain(symptoms: Mapping[str, Any]) -> Optional[RedFlag]:
    if _symptom_present(symptoms, "severe_pain"):
        return RedFlag(
            RF_SEVERE_PAIN,
            "severe pain",
            "Severe or worsening pain needs assessment. " + _CARE_SOON,
        )
    return None


def check_rapid_worsening(
    symptoms: Mapping[str, Any], trend: Optional[trends_mod.TrendResult]
) -> Optional[RedFlag]:
    """Rapid worsening: an explicit symptom, or a steep sustained abnormal trend.

    A steep move is a sustained trend whose net magnitude is at least twice the
    sustained threshold for pH or temperature (a fast climb), in the concerning
    (rising) direction.
    """
    if _symptom_present(symptoms, "rapid_worsening"):
        return RedFlag(
            RF_RAPID_WORSENING,
            "rapid worsening",
            "The wound appears to be worsening quickly. " + _CARE_SOON,
        )
    if trend is not None:
        for metric in ("ph", "skin_temp_c"):
            mt = trend.for_metric(metric)
            thresh = trends_mod._SUSTAINED_DELTA.get(metric, 0.0)
            if mt.ok and mt.direction == trends_mod.RISING and mt.magnitude >= 2 * thresh:
                return RedFlag(
                    RF_RAPID_WORSENING,
                    "rapid worsening",
                    "Readings are climbing quickly. " + _CARE_SOON,
                )
    return None


def check_deep_wound(attrs: Mapping[str, Any], config: ClinicalThresholds) -> Optional[RedFlag]:
    depth = _attr(attrs, "depth_type")
    if isinstance(depth, str) and depth.strip().lower() in {"deep", "gaping", "deep_gaping"}:
        return RedFlag(
            RF_DEEP_WOUND,
            "deep/gaping wound",
            "A deep or gaping wound needs professional assessment. " + _CARE,
        )
    # Unknown depth is surfaced conservatively, never assumed shallow/safe.
    if depth is None and _is_conservative(config):
        return RedFlag(
            RF_DEEP_WOUND,
            "wound depth unknown",
            "Wound depth is unknown and could be serious." + _UNKNOWN_SUFFIX + " " + _CARE,
            from_unknown=True,
        )
    return None


def check_bite_puncture(
    attrs: Mapping[str, Any], symptoms: Mapping[str, Any]
) -> Optional[RedFlag]:
    depth = _attr(attrs, "depth_type")
    is_bite_attr = isinstance(depth, str) and depth.strip().lower() in {
        "bite",
        "puncture",
        "bite_puncture",
    }
    if is_bite_attr or _symptom_present(symptoms, "bite_puncture"):
        return RedFlag(
            RF_BITE_PUNCTURE,
            "bite/puncture wound",
            "Bite and puncture wounds carry a high infection risk. " + _CARE_SOON,
        )
    return None


def check_diabetic(attrs: Mapping[str, Any], config: ClinicalThresholds) -> Optional[RedFlag]:
    value = _attr(attrs, "attr_diabetic")
    if value is True:
        return RedFlag(
            RF_DIABETIC,
            "diabetic user",
            "Wounds in people with diabetes can worsen quickly. " + _CARE,
        )
    if value is None and _is_conservative(config):
        return RedFlag(
            RF_DIABETIC,
            "diabetes status unknown",
            "Diabetes status is unknown." + _UNKNOWN_SUFFIX + " " + _CARE,
            from_unknown=True,
        )
    return None


def check_immunocompromised(
    attrs: Mapping[str, Any], config: ClinicalThresholds
) -> Optional[RedFlag]:
    value = _attr(attrs, "attr_immunocompromised")
    if value is True:
        return RedFlag(
            RF_IMMUNOCOMPROMISED,
            "immunocompromised user",
            "A weakened immune system raises infection risk. " + _CARE,
        )
    if value is None and _is_conservative(config):
        return RedFlag(
            RF_IMMUNOCOMPROMISED,
            "immune status unknown",
            "Immune status is unknown." + _UNKNOWN_SUFFIX + " " + _CARE,
            from_unknown=True,
        )
    return None


def check_no_improvement(
    history: Sequence[Any],
    now,
    config: ClinicalThresholds,
    trend: Optional[trends_mod.TrendResult] = None,
) -> Optional[RedFlag]:
    """No improvement over N days (N from ``config.no_improvement_days``).

    Fires when the usable history spans at least N days AND no metric shows a
    sustained *improving* direction over the trend window (i.e. things are not
    getting better despite enough elapsed time). Improvement is a falling pH or
    falling temperature trend.
    """
    from datetime import timedelta

    n_days = int(config.no_improvement_days)
    usable_ts = [getattr(r, "ts", None) for r in history]
    usable_ts = [t for t in usable_ts if t is not None]
    if len(usable_ts) < 2:
        return None
    span = max(usable_ts) - min(usable_ts)
    if span < timedelta(days=n_days):
        return None

    improving = False
    if trend is not None:
        for metric in ("ph", "skin_temp_c"):
            mt = trend.for_metric(metric)
            if mt.ok and mt.direction == trends_mod.FALLING:
                improving = True
                break
    if improving:
        return None
    return RedFlag(
        RF_NO_IMPROVEMENT,
        f"no improvement over {n_days} days",
        f"The wound has not improved over {n_days} days. " + _CARE,
    )


def check_sustained_abnormal_trend(
    trend: Optional[trends_mod.TrendResult],
) -> Optional[RedFlag]:
    """Sustained abnormal trend: a sustained rising pH or temperature.

    A rising pH or rising temperature sustained across the window is the
    abnormal (concerning) direction. A rising moisture alone is handled by the
    data-driven watch band, not as an escalating red flag.
    """
    if trend is None:
        return None
    for metric in ("ph", "skin_temp_c"):
        mt = trend.for_metric(metric)
        if mt.ok and mt.sustained and mt.direction == trends_mod.RISING:
            return RedFlag(
                RF_SUSTAINED_ABNORMAL_TREND,
                "sustained abnormal trend",
                "Readings have been trending the wrong way. " + _CARE,
            )
    return None


# ===========================================================================
# Aggregate evaluation.
# ===========================================================================
def evaluate(
    attrs: Mapping[str, Any],
    symptoms: Mapping[str, Any],
    trend: Optional[trends_mod.TrendResult],
    config: ClinicalThresholds,
    *,
    history: Optional[Sequence[Any]] = None,
    now=None,
) -> list[RedFlag]:
    """Return every active red flag (order stable by rule declaration).

    ``attrs`` and ``symptoms`` are mappings; a missing/None value is *unknown*
    and is never silently treated as safe. ``history``/``now`` are only needed
    for the no-improvement rule (skipped when not provided).
    """
    attrs = attrs or {}
    symptoms = symptoms or {}
    flags: list[RedFlag] = []

    def add(flag: Optional[RedFlag]) -> None:
        if flag is not None:
            flags.append(flag)

    add(check_spreading_redness(symptoms))
    add(check_pus(symptoms))
    add(check_fever(symptoms))
    add(check_severe_pain(symptoms))
    add(check_rapid_worsening(symptoms, trend))
    add(check_deep_wound(attrs, config))
    add(check_bite_puncture(attrs, symptoms))
    add(check_diabetic(attrs, config))
    add(check_immunocompromised(attrs, config))
    if history is not None and now is not None:
        add(check_no_improvement(history, now, config, trend))
    add(check_sustained_abnormal_trend(trend))
    return flags
