import json
from pathlib import Path
from typing import Any


_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "clinical_thresholds.json"
with _CONFIG_PATH.open(encoding="utf-8") as config_file:
    THRESHOLDS: dict[str, Any] = json.load(config_file)

RED_FLAG_KEYS = (
    "spreading_redness",
    "pus",
    "fever",
    "severe_pain",
    "rapid_worsening",
    "deep_or_gaping_wound",
    "bite_or_puncture",
    "diabetic",
    "immunocompromised",
    "sustained_abnormal_trend",
)


def classify_metrics(reading: dict[str, Any]) -> dict[str, str]:
    ph = reading.get("ph")
    temperature = reading.get("skin_temp_c")
    moisture = reading.get("moisture_pct")

    if ph is None:
        ph_status = "check"
    elif ph > THRESHOLDS["wound_ph"]["infection_risk_above"]:
        ph_status = "high"
    elif ph < THRESHOLDS["wound_ph"]["normal_min"]:
        ph_status = "low"
    elif ph > THRESHOLDS["wound_ph"]["normal_max"]:
        ph_status = "check"
    else:
        ph_status = "normal"

    if temperature is None:
        temperature_status = "check"
    elif temperature > THRESHOLDS["skin_temperature_c"]["normal_max"]:
        temperature_status = "warm"
    elif temperature < THRESHOLDS["skin_temperature_c"]["normal_min"]:
        temperature_status = "check"
    else:
        temperature_status = "normal"

    if moisture is None:
        moisture_status = "check"
    elif moisture < THRESHOLDS["moisture_pct"]["normal_min"]:
        moisture_status = "low"
    elif moisture > THRESHOLDS["moisture_pct"]["normal_max"]:
        moisture_status = "high"
    else:
        moisture_status = "normal"

    return {
        "ph": ph_status,
        "temperature": temperature_status,
        "moisture": moisture_status,
    }


def evaluate_safety(
    reading: dict[str, Any], clinical_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Apply deterministic, conservative rules; never diagnose."""
    context = clinical_context or {}
    metrics = classify_metrics(reading)
    no_improvement_days = int(context.get("no_improvement_after_days", 0) or 0)
    no_improvement_limit = THRESHOLDS["red_flags"]["no_improvement_after_days"]

    red_flag = any(bool(context.get(key, False)) for key in RED_FLAG_KEYS)
    red_flag = red_flag or no_improvement_days >= no_improvement_limit

    if red_flag:
        return {
            "status": "see_doctor_today",
            "reason_code": "red_flag",
            "needs_clinician": True,
            "metric_status": metrics,
        }

    if reading.get("sensor_status") == "dropout" or any(
        reading.get(key) is None
        for key in ("ph", "skin_temp_c", "moisture_pct")
    ):
        return {
            "status": "keep_watching",
            "reason_code": "sensor_dropout",
            "needs_clinician": False,
            "metric_status": metrics,
        }

    if metrics["ph"] == "high":
        return {
            "status": "see_doctor_today",
            "reason_code": "high_wound_ph",
            "needs_clinician": True,
            "metric_status": metrics,
        }

    if any(value != "normal" for value in metrics.values()):
        return {
            "status": "keep_watching",
            "reason_code": "abnormal_reading",
            "needs_clinician": False,
            "metric_status": metrics,
        }

    return {
        "status": "all_good",
        "reason_code": "readings_in_expected_ranges",
        "needs_clinician": False,
        "metric_status": metrics,
    }
