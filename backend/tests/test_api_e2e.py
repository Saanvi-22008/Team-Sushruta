"""End-to-end API tests (FEAT-004).

Covers: valid reading -> 201 with computed status; missing field -> 422;
duplicate -> 409 idempotent; datastore unavailable -> 5xx (never success);
safety config missing -> /health 503; status + timeline return ts-ordered data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import load_config
from _helpers import reading_payload, seed_wound

NOW = datetime.now(timezone.utc)


def test_health_ok_when_config_loaded(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["config_snapshot"].startswith("sha256:")


def test_health_503_when_config_failsafe(client_factory):
    bad = load_config(clinical_path="does-not-exist.yaml", safety_path="nope.yaml")
    assert not bad.loaded
    client = client_factory(bad)

    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"


def test_decision_endpoints_503_when_config_failsafe(client_factory):
    bad = load_config(clinical_path="does-not-exist.yaml", safety_path="nope.yaml")
    client = client_factory(bad)

    # Ingestion depends on the config -> 503.
    r = client.post("/readings", json=reading_payload(ts=NOW))
    assert r.status_code == 503
    # Status + dose likewise.
    assert client.get("/wounds/wound-1/status").status_code == 503
    assert (
        client.post(
            "/wounds/wound-1/dose-requests",
            json={"requested_dose_mj": 10, "requested_duration_s": 10},
        ).status_code
        == 503
    )


def test_valid_reading_returns_201_with_status(client, session_factory):
    seed_wound(session_factory)
    resp = client.post("/readings", json=reading_payload(ts=NOW))
    assert resp.status_code == 201
    body = resp.json()
    assert isinstance(body["reading_id"], int)
    assert body["status"]["wound_id"] == "wound-1"
    assert body["status"]["level"] in {"normal", "watch", "infection-risk", "escalate"}
    assert body["status"]["config_snapshot"].startswith("sha256:")


def test_infection_reading_computes_non_normal_status(client, session_factory):
    seed_wound(session_factory)
    # pH above the infection-risk band -> infection-risk.
    resp = client.post("/readings", json=reading_payload(ts=NOW, ph=8.5))
    assert resp.status_code == 201
    assert resp.json()["status"]["level"] == "infection-risk"


def test_missing_field_returns_422(client, session_factory):
    seed_wound(session_factory)
    payload = reading_payload(ts=NOW)
    del payload["ph"]
    resp = client.post("/readings", json=payload)
    assert resp.status_code == 422


def test_unknown_field_rejected(client, session_factory):
    seed_wound(session_factory)
    payload = reading_payload(ts=NOW)
    payload["injected_threshold"] = 999
    resp = client.post("/readings", json=payload)
    assert resp.status_code == 422


def test_duplicate_reading_returns_409(client, session_factory):
    seed_wound(session_factory)
    payload = reading_payload(ts=NOW)
    first = client.post("/readings", json=payload)
    assert first.status_code == 201
    second = client.post("/readings", json=payload)
    assert second.status_code == 409


def test_datastore_unavailable_returns_5xx(client, session_factory, monkeypatch):
    seed_wound(session_factory)
    # Force the status computation to raise a DB error mid-ingest.
    from sqlalchemy.exc import OperationalError

    from app.api import readings as readings_mod

    def boom(*_a, **_k):
        raise OperationalError("SELECT 1", {}, Exception("datastore down"))

    monkeypatch.setattr(readings_mod.service, "compute_status", boom)
    resp = client.post("/readings", json=reading_payload(ts=NOW))
    assert resp.status_code >= 500
    assert resp.status_code != 201


def test_status_endpoint_404_for_unknown_wound(client):
    resp = client.get("/wounds/ghost/status")
    assert resp.status_code == 404


def test_status_endpoint_returns_current(client, session_factory):
    seed_wound(session_factory)
    client.post("/readings", json=reading_payload(ts=NOW))
    resp = client.get("/wounds/wound-1/status")
    assert resp.status_code == 200
    assert resp.json()["wound_id"] == "wound-1"


def test_timeline_returns_ts_ordered(client, session_factory):
    seed_wound(session_factory)
    t0 = NOW - timedelta(minutes=20)
    t1 = NOW - timedelta(minutes=10)
    t2 = NOW
    for ts in (t2, t0, t1):  # out of order on the wire
        client.post("/readings", json=reading_payload(ts=ts))

    resp = client.get("/wounds/wound-1/timeline")
    assert resp.status_code == 200
    body = resp.json()
    reading_ts = [r["ts"] for r in body["readings"]]
    assert reading_ts == sorted(reading_ts)
    status_ts = [s["ts"] for s in body["statuses"]]
    assert status_ts == sorted(status_ts)
    assert len(body["readings"]) == 3


def test_timeline_respects_from_to_limit(client, session_factory):
    seed_wound(session_factory)
    base = NOW - timedelta(hours=5)
    stamps = [base + timedelta(hours=i) for i in range(5)]
    for ts in stamps:
        client.post("/readings", json=reading_payload(ts=ts))

    resp = client.get(
        "/wounds/wound-1/timeline",
        params={"from": stamps[1].isoformat(), "to": stamps[3].isoformat()},
    )
    assert resp.status_code == 200
    assert len(resp.json()["readings"]) == 3

    limited = client.get("/wounds/wound-1/timeline", params={"limit": 2})
    assert len(limited.json()["readings"]) == 2


def test_batch_returns_207_per_item(client, session_factory):
    seed_wound(session_factory)
    good = reading_payload(ts=NOW)
    dup = reading_payload(ts=NOW)  # same ts -> duplicate of good
    bad = reading_payload(ts=NOW - timedelta(minutes=1))
    del bad["ph"]  # invalid

    resp = client.post("/readings/batch", json=[good, dup, bad])
    assert resp.status_code == 207
    outcomes = [item["outcome"] for item in resp.json()]
    assert outcomes == ["stored", "duplicate", "invalid"]
