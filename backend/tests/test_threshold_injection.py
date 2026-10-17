"""Threshold-injection lock test (FEAT-004).

A request that tries to supply its own threshold / cap / forced status is either
rejected (extra='forbid' -> 422) or ignored; it never changes the computed
status or the dose decision. The server reads limits ONLY from config.
"""

from __future__ import annotations

from datetime import datetime, timezone

from _helpers import reading_payload, seed_wound

NOW = datetime.now(timezone.utc)


def test_reading_rejects_injected_threshold_fields(client, session_factory):
    seed_wound(session_factory)
    for bad_field in (
        "ph_infection_risk_above",
        "forced_level",
        "level",
        "machine_code",
        "max_dose_mj",
    ):
        payload = reading_payload(ts=NOW)
        payload[bad_field] = 0.0
        resp = client.post("/readings", json=payload)
        assert resp.status_code == 422, f"{bad_field} should be rejected"


def test_injected_fields_do_not_change_computed_status(client, session_factory):
    seed_wound(session_factory)
    # Baseline: an infection-risk pH computes infection-risk.
    base = client.post("/readings", json=reading_payload(ts=NOW, ph=8.5))
    assert base.status_code == 201
    assert base.json()["status"]["level"] == "infection-risk"

    # A second wound where the caller ALSO tries to force 'normal' via injected
    # fields -> rejected, so the computed status is unaffected (never forced).
    seed_wound(session_factory, wound_id="wound-2", device_id="dev-1")
    payload = reading_payload(ts=NOW, ph=8.5, wound_id="wound-2")
    payload["forced_level"] = "normal"
    payload["ph_infection_risk_above"] = 99.0  # try to raise the band so pH looks fine
    forced = client.post("/readings", json=payload)
    assert forced.status_code == 422  # injection rejected outright

    # Submitting the clean reading still computes infection-risk (config bands win).
    clean = client.post("/readings", json=reading_payload(ts=NOW, ph=8.5, wound_id="wound-2"))
    assert clean.json()["status"]["level"] == "infection-risk"


def test_dose_request_cannot_override_caps(client, session_factory):
    seed_wound(session_factory)
    client.post("/readings", json=reading_payload(ts=NOW))

    # Try to inject a huge cap so an over-limit dose would be "allowed".
    resp = client.post(
        "/wounds/wound-1/dose-requests",
        json={
            "requested_dose_mj": 100000,
            "requested_duration_s": 30,
            "max_dose_mj": 100000,
        },
    )
    # extra='forbid' rejects the injected cap -> 422 (never honored).
    assert resp.status_code == 422


def test_dose_over_limit_denied_even_without_injection(client, session_factory):
    """Even a clean over-limit request is denied from config (no silent clamp)."""
    seed_wound(session_factory)
    client.post("/readings", json=reading_payload(ts=NOW))
    resp = client.post(
        "/wounds/wound-1/dose-requests",
        json={"requested_dose_mj": 100000, "requested_duration_s": 30},
    )
    assert resp.status_code == 409
