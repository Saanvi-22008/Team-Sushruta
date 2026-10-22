"""Trend watch: an experimental, advisory early-warning score.

It looks at the last WINDOW readings and estimates the chance that pH will cross
the placeholder "see a doctor" line within the next few readings.

It NEVER changes the safety status. The status comes only from the rules in
backend/safety.py. The model is trained on synthetic data (see ml/MODEL_CARD.md)
and is loaded from plain JSON, so no machine-learning library is needed here.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from ml.features import WINDOW, extract

MODEL_PATH = Path(__file__).resolve().parents[1] / "ml" / "model.json"
WINDOW_NEEDED = WINDOW
WATCH = 0.5      # about 69% of upcoming crossings caught, many false alarms
RISING = 0.85    # about 95% precision, about 41% recall (on synthetic test data)


@lru_cache(maxsize=1)
def load_model() -> dict[str, Any] | None:
    try:
        return json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def score(window: list[dict[str, Any]]) -> float:
    """Probability-like score in 0..1 for exactly `window` readings (oldest first)."""
    model = load_model()
    if model is None:
        raise RuntimeError("trend model file is missing")
    features = extract(window)
    z = model["intercept"]
    for value, mean, scale, weight in zip(features, model["mean"], model["scale"], model["coef"]):
        z += weight * ((value - mean) / (scale or 1.0))
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def level(risk: float) -> str:
    if risk >= RISING:
        return "rising"
    if risk >= WATCH:
        return "watch"
    return "low"


def assess(readings: list[dict[str, Any]]) -> dict[str, Any]:
    """`readings` oldest first. Returns an advisory dict; never raises for short input."""
    model = load_model()
    base = {"advisory_only": True, "trained_on": "synthetic data", "experimental": True}
    if model is None:
        return {**base, "available": False, "reason": "model_missing"}
    need = model["window"]
    if len(readings) < need:
        return {**base, "available": False, "reason": "not_enough_readings", "have": len(readings), "need": need}
    risk = score(readings[-need:])
    return {**base, "available": True, "risk": round(risk, 3), "level": level(risk), "window": need}
