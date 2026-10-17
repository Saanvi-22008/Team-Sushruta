"""Serial-port ingestion bridge.

A :class:`SerialBridge` reads one JSON object per line from a serial port (the
smart-bandage firmware prints one reading per line) and POSTs each well-formed
line to the ingestion API as a ``ReadingIn``. It is a STANDALONE process, not
part of the API server (invariant: edge sources feed the same validation path
over HTTP; they do not import the request-handling internals).

Resilience (Req 13): a malformed or partial line is skipped with a logged
warning and the stream continues — one bad frame never crashes the bridge. Any
transport/HTTP error for a single reading is likewise logged and skipped so a
transient API hiccup does not drop the whole session.

The serial port and the HTTP client are both injected as simple objects so the
bridge can be driven by a fake transport in tests (no real hardware, no network):

- ``serial_port`` must be line-iterable and yield ``bytes`` or ``str`` lines
  (``pyserial``'s ``Serial`` is iterable and yields ``bytes``).
- ``poster`` is any callable ``poster(reading: dict) -> None`` that delivers one
  validated reading dict to the ingestion API; :class:`HttpPoster` is the
  default production implementation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable, Optional

from app.core.schemas import ReadingIn

logger = logging.getLogger("sushruta.serial_bridge")

# A poster takes one ReadingIn-shaped dict and delivers it to the API.
Poster = Callable[[dict[str, Any]], None]


def _decode_line(raw: Any) -> str:
    """Return a stripped text line from a bytes/str serial frame."""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace").strip()
    return str(raw).strip()


class SerialBridge:
    """Read JSON-per-line readings off a serial port and POST each to the API.

    Parameters
    ----------
    serial_port:
        A line-iterable serial source (``pyserial.Serial`` or any iterable of
        ``bytes``/``str`` lines). Tests pass a list/iterator of fake lines.
    poster:
        Callable that delivers one well-formed reading to the ingestion API.
    """

    source = "serial"

    def __init__(self, serial_port: Iterable[Any], poster: Poster) -> None:
        self._serial_port = serial_port
        self._poster = poster

    def _handle_line(self, raw: Any) -> bool:
        """Validate+POST one line. Return True iff a reading was delivered."""
        text = _decode_line(raw)
        if not text:
            return False  # blank/keep-alive line

        try:
            obj = json.loads(text)
        except (ValueError, TypeError) as exc:
            logger.warning("skipping malformed serial line (not JSON): %s", exc)
            return False
        if not isinstance(obj, dict):
            logger.warning("skipping serial line: expected a JSON object, got %s", type(obj).__name__)
            return False

        # Validate against the strict wire contract before delivery so a partial
        # or wrong-typed object is skipped here rather than bouncing off the API.
        try:
            reading = ReadingIn.model_validate(obj)
        except Exception as exc:  # pydantic ValidationError (and any coercion error)
            logger.warning("skipping serial line: failed ReadingIn validation: %s", exc)
            return False

        payload = reading.model_dump(mode="json")
        try:
            self._poster(payload)
        except Exception as exc:  # transport/HTTP error for this one reading
            logger.warning("failed to POST serial reading (skipping): %s", exc)
            return False
        return True

    def run(self, *, limit: Optional[int] = None) -> int:
        """Consume the serial stream, POSTing each well-formed reading.

        Returns the number of readings successfully delivered. ``limit`` caps the
        number of raw lines read (handy for tests / bounded demo runs); ``None``
        reads until the port iterator is exhausted.
        """
        delivered = 0
        for i, raw in enumerate(self._serial_port):
            if limit is not None and i >= limit:
                break
            if self._handle_line(raw):
                delivered += 1
        return delivered
