import pytest

from backend.safety import classify_metrics, evaluate_safety
from backend.schemas import ReadingCreate


def reading(**changes):
    values = {
        "ph": 6.8,
        "skin_temp_c": 36.7,
        "moisture_pct": 42,
        "sensor_status": "available",
    }
    values.update(changes)
    return values


@pytest.mark.parametrize(
    "flag",
    [
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
    ],
)
def test_each_red_flag_escalates(flag):
    result = evaluate_safety(reading(), {flag: True})
    assert result["status"] == "see_doctor_today"
    assert result["reason_code"] == "red_flag"
    assert result["needs_clinician"] is True


def test_no_improvement_after_placeholder_days_escalates():
    result = evaluate_safety(reading(), {"no_improvement_after_days": 7})
    assert result["status"] == "see_doctor_today"
    assert result["reason_code"] == "red_flag"


def test_high_wound_ph_escalates():
    result = evaluate_safety(reading(ph=7.8))
    assert result["status"] == "see_doctor_today"
    assert result["reason_code"] == "high_wound_ph"


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (reading(), "all_good"),
        (reading(ph=6.0), "keep_watching"),
        (reading(skin_temp_c=37.6), "keep_watching"),
        (reading(moisture_pct=85), "keep_watching"),
        (reading(sensor_status="dropout", ph=None, skin_temp_c=None, moisture_pct=None), "keep_watching"),
        (reading(ph=None), "keep_watching"),
    ],
)
def test_non_escalation_reading_states(values, expected):
    assert evaluate_safety(values)["status"] == expected


def test_metric_status_uses_configured_placeholder_bands():
    result = classify_metrics(reading(ph=7.8, skin_temp_c=37.6, moisture_pct=85))
    assert result == {"ph": "high", "temperature": "warm", "moisture": "high"}


def test_reading_rejects_impossible_measurements_and_naive_timestamp():
    values = {
        "device_id": "demo",
        "wound_id": "wound",
        "ts": "2026-10-21T12:00:00",
        "ph": 18,
        "skin_temp_c": 36.7,
        "moisture_pct": 42,
        "battery_pct": 92,
        "sensor_status": "available",
    }
    with pytest.raises(Exception):
        ReadingCreate.model_validate(values)
