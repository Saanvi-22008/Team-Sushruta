"""Turn a short window of patch readings into numbers a model can use.

Pure Python on purpose: the same file is used when training (on a laptop) and
when serving (inside the API container), so the two can never drift apart.
"""

from __future__ import annotations

from typing import Any, Sequence

WINDOW = 6          # readings the model looks at
HORIZON = 4         # readings ahead it tries to foresee
PH_LINE = 7.5       # placeholder "see a doctor" pH line (config/clinical_thresholds.json)

FEATURE_NAMES = [
    "ph_last", "ph_mean", "ph_slope",
    "temp_last", "temp_mean", "temp_slope",
    "moisture_last", "moisture_mean", "moisture_slope",
    "ph_gap_to_line", "missing_fraction",
]
METRICS = ("ph", "skin_temp_c", "moisture_pct")


def _slope(values: Sequence[float]) -> float:
    """Least-squares slope per reading."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den if den else 0.0


def _stats(window: Sequence[dict[str, Any]], key: str) -> tuple[float, float, float, int]:
    values = [float(r[key]) for r in window if r.get(key) is not None]
    if not values:
        return 0.0, 0.0, 0.0, len(window)
    return values[-1], sum(values) / len(values), _slope(values), len(window) - len(values)


def extract(window: Sequence[dict[str, Any]]) -> list[float]:
    """Features for exactly WINDOW readings (oldest first). Missing values are skipped."""
    if len(window) != WINDOW:
        raise ValueError(f"need exactly {WINDOW} readings")
    ph_last, ph_mean, ph_slope, ph_missing = _stats(window, "ph")
    t_last, t_mean, t_slope, t_missing = _stats(window, "skin_temp_c")
    m_last, m_mean, m_slope, m_missing = _stats(window, "moisture_pct")
    missing = (ph_missing + t_missing + m_missing) / (3 * WINDOW)
    return [
        ph_last, ph_mean, ph_slope,
        t_last, t_mean, t_slope,
        m_last, m_mean, m_slope,
        PH_LINE - ph_last if ph_missing < WINDOW else 0.0,
        missing,
    ]
