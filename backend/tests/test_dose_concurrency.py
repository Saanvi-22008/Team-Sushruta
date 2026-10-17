"""Dose concurrency test (FEAT-004).

Concurrent dose requests for the SAME wound must be evaluated against the
committed grant record under the per-wound lock, so at most the allowed number
is granted and the rest are denied with the gap reason. With the configured
``min_gap_s`` (hours), exactly one of a burst can be granted.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from _helpers import reading_payload, seed_wound
from app.safety.dose import REASON_WITHIN_GAP


def test_concurrent_dose_requests_only_one_grant(client, session_factory):
    seed_wound(session_factory)
    client.post("/readings", json=reading_payload(ts=datetime.now(timezone.utc)))

    body = {"requested_dose_mj": 10.0, "requested_duration_s": 30.0}

    def fire(_i):
        return client.post("/wounds/wound-1/dose-requests", json=body)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(fire, range(8)))

    codes = [r.status_code for r in responses]
    granted = [c for c in codes if c == 201]
    denied = [c for c in codes if c == 409]

    # The per-wound lock + committed-grant evaluation means the gap cap holds:
    # exactly one grant, every other request denied (never more than allowed).
    assert len(granted) == 1
    assert len(denied) == len(responses) - 1

    # Each denial is the gap reason (racing against the committed grant).
    gap_denials = [
        r for r in responses if r.status_code == 409 and r.json()["reason_code"] == REASON_WITHIN_GAP
    ]
    assert len(gap_denials) == len(denied)

    # The committed grant record shows exactly one granted row.
    from app.core.models_db import DoseRequest

    s = session_factory()
    try:
        rows = s.query(DoseRequest).filter_by(wound_id="wound-1", outcome="granted").all()
        assert len(rows) == 1
    finally:
        s.close()
