#!/usr/bin/env python
"""Demo driver: push a seeded simulator scenario into a running API.

This is the one-command demo for the dashboard. It generates a reproducible
scenario (``--seed``) and POSTs each reading to a running ingestion API
(``--post <base_url>``), pacing them with ``--interval`` so the live dashboard
updates as the trajectory unfolds.

The data is SYNTHETIC and clearly flagged simulated end-to-end — this is a proof
of concept, NOT a medical device.

Usage
-----
    # from the repo root, with the API already running (see README):
    python scripts/run_simulator.py --scenario early_infection --seed 1 \
        --post http://127.0.0.1:8000 --interval 1.0

    # fastest demo (no pacing):
    python scripts/run_simulator.py --scenario healing --post http://127.0.0.1:8000 --interval 0

Scenarios: healing, early_infection, heavy_exudate, inflammation_spike, sensor_dropout.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

# Make ``app`` importable whether run from the repo root or the backend dir.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_REPO_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.ingestion.http_device import HttpDevice, HttpDeviceError  # noqa: E402
from app.ingestion.simulator import SCENARIOS, SimulatorSource  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive a seeded simulator scenario into a running Sushruta API.",
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="early_infection",
        help="Which synthetic trajectory to emit (default: early_infection).",
    )
    parser.add_argument(
        "--seed", type=int, default=1, help="RNG seed for a reproducible run (default: 1)."
    )
    parser.add_argument(
        "--post",
        default="http://127.0.0.1:8000",
        metavar="BASE_URL",
        help="Base URL of the running API (default: http://127.0.0.1:8000).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds to wait between POSTs for a live-feel demo (default: 1.0; 0 = as fast as possible).",
    )
    parser.add_argument(
        "--count", type=int, default=12, help="Number of readings to emit (default: 12)."
    )
    parser.add_argument(
        "--wound-id", default="sim-wound-1", help="Wound id stamped on every reading."
    )
    parser.add_argument(
        "--device-id", default="sim-device-1", help="Device id stamped on every reading."
    )
    return parser.parse_args(argv)


def build_source(args: argparse.Namespace) -> SimulatorSource:
    """Build a simulator whose readings end at ~now so they ingest as FRESH.

    The simulator's default epoch is fixed for reproducibility, but a live demo
    needs recent timestamps or every reading would be stale. We anchor the LAST
    reading near the current time (spaced one real-ish step apart) so the
    dashboard shows a current, non-stale status.
    """
    interval_s = 60  # wire spacing between simulated readings (not the POST pace)
    start = datetime.now(timezone.utc) - timedelta(seconds=interval_s * (args.count - 1))
    return SimulatorSource(
        args.scenario,
        seed=args.seed,
        count=args.count,
        interval_s=interval_s,
        start=start,
        device_id=args.device_id,
        wound_id=args.wound_id,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a declared dependency
        print("httpx is required to POST readings; install the dev dependencies.", file=sys.stderr)
        return 2

    source = build_source(args)
    print(
        f"Simulating '{args.scenario}' (seed={args.seed}, count={args.count}) "
        f"-> POST {args.post}/readings  [SYNTHETIC DATA — not a medical device]"
    )

    delivered = 0
    with httpx.Client(timeout=10.0) as client:
        device = HttpDevice(client, base_url=args.post)
        readings = list(source.readings())
        for i, reading in enumerate(readings):
            try:
                body = device.post_reading(reading)
            except HttpDeviceError as exc:
                print(f"  [{i + 1}/{len(readings)}] rejected ({exc.status_code}): {exc.detail}", file=sys.stderr)
                continue
            except httpx.HTTPError as exc:
                print(f"  [{i + 1}/{len(readings)}] transport error: {exc}", file=sys.stderr)
                continue
            delivered += 1
            status = body.get("status", {})
            print(
                f"  [{i + 1}/{len(readings)}] reading_id={body.get('reading_id')} "
                f"level={status.get('level')} ({status.get('machine_code')})"
            )
            if args.interval > 0 and i < len(readings) - 1:
                time.sleep(args.interval)

    print(f"Done: {delivered}/{len(readings)} readings ingested.")
    return 0 if delivered > 0 else 1


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
