"""Serial-bridge tests (FEAT-005).

No real serial hardware and no network: the serial port is a plain list of
fake lines (bytes/str) and the poster is a mock that captures delivered
readings. Proves a malformed/partial line is skipped (warning logged) and the
stream continues, and that a well-formed JSON line is POSTed as a validated
``ReadingIn``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.ingestion.serial_bridge import SerialBridge


class RecordingPoster:
    """A mock transport: records each reading dict handed to it."""

    def __init__(self) -> None:
        self.posted: list[dict] = []

    def __call__(self, reading: dict) -> None:
        self.posted.append(reading)


def _reading_line(**overrides) -> bytes:
    payload = {
        "device_id": "dev-1",
        "wound_id": "wound-1",
        "ts": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc).isoformat(),
        "ph": 7.0,
        "skin_temp_c": 32.0,
        "moisture_pct": 45.0,
        "battery_pct": 95.0,
        "sensor_status": "ok",
    }
    payload.update(overrides)
    return (json.dumps(payload) + "\n").encode("utf-8")


def test_well_formed_line_is_posted_as_reading():
    poster = RecordingPoster()
    bridge = SerialBridge([_reading_line()], poster)

    delivered = bridge.run()

    assert delivered == 1
    assert len(poster.posted) == 1
    posted = poster.posted[0]
    assert posted["device_id"] == "dev-1"
    assert posted["wound_id"] == "wound-1"
    assert posted["sensor_status"] == "ok"
    # No forbidden extras leaked through the strict contract.
    assert "simulated" not in posted


def test_malformed_line_skipped_and_stream_continues(caplog):
    poster = RecordingPoster()
    lines = [
        b"{not valid json",             # malformed -> skipped
        b'{"partial": true}\n',         # valid JSON, missing required fields -> skipped
        _reading_line(ph=7.2),          # well-formed -> delivered
    ]
    bridge = SerialBridge(lines, poster)

    with caplog.at_level(logging.WARNING, logger="sushruta.serial_bridge"):
        delivered = bridge.run()

    # Only the one good line was delivered; the bridge did not crash.
    assert delivered == 1
    assert len(poster.posted) == 1
    assert poster.posted[0]["ph"] == 7.2
    # A warning was logged for the skipped lines.
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_blank_lines_ignored():
    poster = RecordingPoster()
    bridge = SerialBridge([b"", b"   ", b"\n", _reading_line()], poster)
    assert bridge.run() == 1


def test_non_object_json_skipped():
    poster = RecordingPoster()
    # A JSON array / scalar is valid JSON but not a reading object.
    bridge = SerialBridge([b"[1,2,3]\n", b"42\n", _reading_line()], poster)
    assert bridge.run() == 1


def test_poster_error_is_skipped_not_fatal(caplog):
    calls = {"n": 0}

    def flaky(reading: dict) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient API error")

    bridge = SerialBridge([_reading_line(ph=7.1), _reading_line(ph=7.3)], flaky)
    with caplog.at_level(logging.WARNING, logger="sushruta.serial_bridge"):
        delivered = bridge.run()

    # First POST failed (skipped), second succeeded -> stream continued.
    assert delivered == 1
    assert calls["n"] == 2


def test_str_lines_also_accepted():
    poster = RecordingPoster()
    line = _reading_line().decode("utf-8")  # str instead of bytes
    bridge = SerialBridge([line], poster)
    assert bridge.run() == 1


def test_limit_caps_lines_read():
    poster = RecordingPoster()
    lines = [_reading_line(ts=datetime(2026, 1, 1, 12, i, tzinfo=timezone.utc).isoformat()) for i in range(5)]
    bridge = SerialBridge(lines, poster)
    delivered = bridge.run(limit=2)
    assert delivered == 2
    assert len(poster.posted) == 2
