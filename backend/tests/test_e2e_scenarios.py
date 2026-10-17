"""End-to-end scenario trajectory tests (FEAT-005).

Each seeded simulator scenario is driven THROUGH THE REAL API (readings POSTed
over the in-process ``TestClient`` via the ``HttpDevice`` edge path, then the
status read back from ``GET /wounds/{id}/status``) and the resulting trajectory
is asserted:

- ``healing``          -> normal
- ``early_infection``  -> infection-risk
- ``heavy_exudate``    -> watch (high moisture, no infection band crossed)
- ``inflammation_spike`` -> infection-risk
- ``sensor_dropout``   -> reduced confidence (stale and/or degraded sensor)

The readings are spaced so the LAST one lands inside the freshness window (a
fresh, non-stale status) while fewer than three readings fall inside the trend
window and the whole history spans under the no-improvement horizon — so the
status reflects the latest reading's bands rather than a trend/no-improvement
red flag. The engine itself is proven exhaustively in the FEAT-003 unit tests;
this file proves the full ingest->evaluate->read path end to end.

Note on the ``simulated`` marker: the strict ``ReadingIn`` wire contract
(``extra='forbid'``) deliberately does NOT carry a ``simulated`` field, so a
reading POSTed over HTTP — including from this demo driver — is recorded as a
real HTTP-source reading (``simulated=False``). The simulator stamps
``simulated=True`` on its emitted dicts and that is asserted end-to-end in the
simulator unit tests; it is not injectable through the public ingest API.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ingestion.http_device import HttpDevice
from app.ingestion.simulator import SimulatorSource
from _helpers import seed_wound

# 4 readings, 36h apart: span 4.5 days (< the 5-day no-improvement horizon) and
# only the final reading inside the 24h trend + 30min freshness windows.
_COUNT = 4
_INTERVAL_S = 36 * 3600
_SEED = 1
_WOUND = "sim-wound-1"
_DEVICE = "sim-device-1"


def _drive_scenario(client, scenario: str) -> dict:
    """POST a seeded scenario through the API; return the final StatusOut JSON."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(seconds=_INTERVAL_S * (_COUNT - 1))
    source = SimulatorSource(
        scenario,
        seed=_SEED,
        count=_COUNT,
        interval_s=_INTERVAL_S,
        start=start,
        device_id=_DEVICE,
        wound_id=_WOUND,
    )
    device = HttpDevice(client)
    last_status: dict | None = None
    for reading in source.readings():
        body = device.post_reading(reading)
        last_status = body["status"]

    assert last_status is not None, f"scenario '{scenario}' emitted no readings"
    # Read the status back from the dedicated endpoint (recomputed live).
    resp = client.get(f"/wounds/{_WOUND}/status")
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture()
def seeded(session_factory):
    # Known-safe wound attributes so the trajectory is purely data-driven
    # (unknown attrs would conservatively escalate — see FEAT-003/-004 findings).
    seed_wound(
        session_factory,
        wound_id=_WOUND,
        device_id=_DEVICE,
        attr_diabetic=False,
        attr_immunocompromised=False,
        depth_type="superficial",
    )


def test_healing_trajectory_is_normal(client, seeded):
    status = _drive_scenario(client, "healing")
    assert status["level"] == "normal"
    assert status["stale"] is False


def test_early_infection_trajectory_is_infection_risk(client, seeded):
    status = _drive_scenario(client, "early_infection")
    assert status["level"] == "infection-risk"


def test_heavy_exudate_trajectory_is_watch(client, seeded):
    status = _drive_scenario(client, "heavy_exudate")
    assert status["level"] == "watch"


def test_inflammation_spike_trajectory_is_infection_risk(client, seeded):
    status = _drive_scenario(client, "inflammation_spike")
    assert status["level"] == "infection-risk"


def test_sensor_dropout_trajectory_reduces_confidence(client, seeded):
    status = _drive_scenario(client, "sensor_dropout")
    # Dropout surfaces as reduced confidence, driven by staleness and/or a
    # degraded sensor — never silently presented as a clean normal.
    assert status["confidence"] == "reduced"
    assert status["stale"] is True or status["sensor_health"] in {"drifting", "disconnected"}


def test_scenario_readings_persist_in_timeline(client, seeded):
    """Every driven reading is persisted and readable back ts-ordered."""
    _drive_scenario(client, "healing")
    timeline = client.get(f"/wounds/{_WOUND}/timeline").json()
    assert len(timeline["readings"]) == _COUNT
    ts = [r["ts"] for r in timeline["readings"]]
    assert ts == sorted(ts)
