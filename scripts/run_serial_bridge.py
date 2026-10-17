#!/usr/bin/env python
"""Standalone entry point for the serial-port ingestion bridge.

Opens a serial port (the smart-bandage firmware prints one JSON reading per
line) and forwards each well-formed line to a running ingestion API. This runs
as its OWN process, separate from the API server, so edge hardware feeds the
same validation path over HTTP.

Usage
-----
    python scripts/run_serial_bridge.py --port COM3 --baud 115200 \
        --post http://127.0.0.1:8000

A malformed/partial line is skipped (warning logged) and the stream continues;
the bridge does not crash on one bad frame.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Make ``app`` importable whether run from the repo root or the backend dir.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_REPO_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.ingestion.http_device import HttpDevice  # noqa: E402
from app.ingestion.serial_bridge import SerialBridge  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Forward serial-port readings to a running Sushruta API.",
    )
    parser.add_argument("--port", required=True, help="Serial port (e.g. COM3 or /dev/ttyUSB0).")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200).")
    parser.add_argument(
        "--post",
        default="http://127.0.0.1:8000",
        metavar="BASE_URL",
        help="Base URL of the running API (default: http://127.0.0.1:8000).",
    )
    parser.add_argument(
        "--timeout", type=float, default=1.0, help="Serial read timeout in seconds (default: 1.0)."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        import httpx
        import serial  # pyserial
    except ImportError as exc:  # pragma: no cover - declared dependencies
        print(f"missing dependency: {exc}", file=sys.stderr)
        return 2

    try:
        serial_port = serial.Serial(args.port, args.baud, timeout=args.timeout)
    except Exception as exc:  # serial.SerialException and friends
        print(f"could not open serial port {args.port!r}: {exc}", file=sys.stderr)
        return 2

    print(
        f"Serial bridge: {args.port}@{args.baud} -> POST {args.post}/readings  "
        f"[press Ctrl-C to stop]"
    )
    with httpx.Client(timeout=10.0) as client:
        device = HttpDevice(client, base_url=args.post)
        bridge = SerialBridge(serial_port, device.post_reading)
        try:
            delivered = bridge.run()
        except KeyboardInterrupt:  # pragma: no cover - manual stop
            print("\nstopped.")
            return 0
        finally:
            serial_port.close()
    print(f"Done: {delivered} readings ingested.")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
