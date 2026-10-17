"""Fail-safe configuration loader for the Sushruta safety core.

Parses ``config/clinical_thresholds.yaml`` and ``config/safety_limits.yaml`` into
immutable (frozen) dataclasses and computes a stable sha256 snapshot over the
canonicalised parsed config.

SAFETY INVARIANT (context key_patterns #8): a missing or unparseable safety
config MUST NOT fall back to an unsafe default. The loader returns a
:class:`SafetyConfig` with ``load_error`` set and no usable thresholds instead
of raising into a default. Callers (e.g. ``/health`` and decision endpoints)
treat ``load_error`` as a hard 503 / deny-closed signal.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# Repo root = backend/app/core/config.py -> parents[3] == worktree root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CLINICAL_PATH = _REPO_ROOT / "config" / "clinical_thresholds.yaml"
DEFAULT_SAFETY_PATH = _REPO_ROOT / "config" / "safety_limits.yaml"


@dataclass(frozen=True)
class Range:
    min: float
    max: float


@dataclass(frozen=True)
class ClinicalThresholds:
    plausible_ph: Range
    plausible_skin_temp_c: Range
    plausible_moisture_pct: Range
    plausible_battery_pct: Range
    freshness_window_s: int
    clock_skew_tolerance_s: int
    low_battery_pct: float
    trend_window_s: int
    ph_watch_above: float
    ph_infection_risk_above: float
    skin_temp_c_watch_above: float
    skin_temp_c_infection_risk_above: float
    moisture_pct_watch_above: float
    no_improvement_days: int
    unknown_attr_policy: str


@dataclass(frozen=True)
class DoseLimits:
    max_dose_mj: float
    max_session_s: float
    min_gap_s: float
    max_daily_sessions: int
    clamp: bool
    block_on_escalate: bool


@dataclass(frozen=True)
class SafetyConfig:
    """Fully-loaded safety configuration plus its integrity snapshot.

    When ``load_error`` is truthy, ``clinical`` and ``dose`` are ``None`` and
    the config MUST NOT be used to make any decision (fail-safe).
    """

    clinical: Optional[ClinicalThresholds]
    dose: Optional[DoseLimits]
    config_snapshot: Optional[str]
    load_error: Optional[str] = None
    error_paths: tuple[str, ...] = field(default_factory=tuple)

    @property
    def loaded(self) -> bool:
        return self.load_error is None


def _canonical_snapshot(clinical_raw: dict, safety_raw: dict) -> str:
    """Stable sha256 over the canonicalised parsed config.

    Identical input dicts always produce an identical snapshot: JSON is dumped
    with sorted keys so ordering in the YAML file does not change the hash.
    """
    canonical = json.dumps(
        {"clinical_thresholds": clinical_raw, "safety_limits": safety_raw},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"config file {path} did not parse to a mapping")
    return data


def _build_clinical(raw: dict) -> ClinicalThresholds:
    plausible = raw["plausible"]
    return ClinicalThresholds(
        plausible_ph=Range(**plausible["ph"]),
        plausible_skin_temp_c=Range(**plausible["skin_temp_c"]),
        plausible_moisture_pct=Range(**plausible["moisture_pct"]),
        plausible_battery_pct=Range(**plausible["battery_pct"]),
        freshness_window_s=int(raw["freshness_window_s"]),
        clock_skew_tolerance_s=int(raw["clock_skew_tolerance_s"]),
        low_battery_pct=float(raw["low_battery_pct"]),
        trend_window_s=int(raw["trend_window_s"]),
        ph_watch_above=float(raw["ph"]["watch_above"]),
        ph_infection_risk_above=float(raw["ph"]["infection_risk_above"]),
        skin_temp_c_watch_above=float(raw["skin_temp_c"]["watch_above"]),
        skin_temp_c_infection_risk_above=float(raw["skin_temp_c"]["infection_risk_above"]),
        moisture_pct_watch_above=float(raw["moisture_pct"]["watch_above"]),
        no_improvement_days=int(raw["no_improvement_days"]),
        unknown_attr_policy=str(raw["unknown_attr_policy"]),
    )


def _build_dose(raw: dict) -> DoseLimits:
    dose = raw["dose"]
    return DoseLimits(
        max_dose_mj=float(dose["max_dose_mj"]),
        max_session_s=float(dose["max_session_s"]),
        min_gap_s=float(dose["min_gap_s"]),
        max_daily_sessions=int(dose["max_daily_sessions"]),
        clamp=bool(dose["clamp"]),
        block_on_escalate=bool(dose["block_on_escalate"]),
    )


def _fail_safe(reason: str, paths: tuple[str, ...]) -> SafetyConfig:
    """Return a config object that is explicitly unusable (no unsafe default)."""
    return SafetyConfig(
        clinical=None,
        dose=None,
        config_snapshot=None,
        load_error=reason,
        error_paths=paths,
    )


def load_config(
    clinical_path: Path | str | None = None,
    safety_path: Path | str | None = None,
) -> SafetyConfig:
    """Load both config files, failing safe on any error.

    On a missing file, unparseable YAML, or a structurally invalid document the
    returned :class:`SafetyConfig` has ``load_error`` set, ``clinical``/``dose``
    ``None`` and ``config_snapshot`` ``None`` — never a usable default.
    """
    clinical_path = Path(clinical_path) if clinical_path else DEFAULT_CLINICAL_PATH
    safety_path = Path(safety_path) if safety_path else DEFAULT_SAFETY_PATH
    paths = (str(clinical_path), str(safety_path))

    try:
        clinical_raw = _load_yaml(clinical_path)
        safety_raw = _load_yaml(safety_path)
    except FileNotFoundError as exc:
        return _fail_safe(f"safety config missing: {exc}", paths)
    except (yaml.YAMLError, ValueError, OSError) as exc:
        return _fail_safe(f"safety config unparseable: {exc}", paths)

    try:
        clinical = _build_clinical(clinical_raw)
        dose = _build_dose(safety_raw)
    except (KeyError, TypeError, ValueError) as exc:
        return _fail_safe(f"safety config structurally invalid: {exc}", paths)

    snapshot = _canonical_snapshot(clinical_raw, safety_raw)
    return SafetyConfig(
        clinical=clinical,
        dose=dose,
        config_snapshot=snapshot,
        load_error=None,
    )
