"""Shared API dependencies: config access, per-wound locks, reading adapters.

The FastAPI app holds a single :class:`SafetyConfig` (loaded at startup) and a
registry of per-wound locks. These are exposed as dependencies so endpoints can
fail-closed (503) when the config did not load and serialise dose requests per
wound (invariant #6).
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import SafetyConfig
from app.core.db import get_session
from app.core.models_db import Reading
from app.ingestion.validator import FLAG_OK

__all__ = [
    "ReadingAdapter",
    "get_config",
    "require_config",
    "get_wound_lock",
    "utcnow",
    "get_session",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReadingAdapter:
    """Wrap a persisted :class:`Reading` so the pure engine can consume it.

    The rules/trends/staleness modules duck-type on ``ts``, the metric
    attributes, ``sensor_status``, ``battery_pct``, ``simulated`` and
    ``has_usable(metric)``. A DB row stores usability as ``field_flags`` JSON;
    this adapter exposes the SAME gate the in-memory ``ValidatedReading`` uses so
    a flagged (out_of_range / invalid_timestamp) value cannot lower status.
    """

    __slots__ = (
        "id",
        "ts",
        "ph",
        "skin_temp_c",
        "moisture_pct",
        "battery_pct",
        "sensor_status",
        "simulated",
        "_flags",
    )

    def __init__(self, row: Reading) -> None:
        self.id = row.id
        # SQLite does not persist tzinfo; the engine/staleness checks compare
        # against a tz-aware ``now``, so normalise a naive ts to UTC.
        ts = row.ts
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        self.ts = ts
        self.ph = row.ph
        self.skin_temp_c = row.skin_temp_c
        self.moisture_pct = row.moisture_pct
        self.battery_pct = row.battery_pct
        self.sensor_status = row.sensor_status
        self.simulated = bool(row.simulated)
        self._flags = dict(row.field_flags or {})

    def has_usable(self, metric: str) -> bool:
        return self._flags.get(metric, FLAG_OK) == FLAG_OK


# ---------------------------------------------------------------------------
# Config dependency.
# ---------------------------------------------------------------------------
def get_config(request: Request) -> SafetyConfig:
    """Return the app-held SafetyConfig (may be in fail-safe)."""
    return request.app.state.safety_config


def require_config(config: SafetyConfig = Depends(get_config)) -> SafetyConfig:
    """Dependency for decision endpoints: 503 when the config is in fail-safe."""
    if not config.loaded:
        raise HTTPException(
            status_code=503,
            detail="Safety configuration unavailable; decisions are refused.",
        )
    return config


# ---------------------------------------------------------------------------
# Per-wound locks (serialise dose requests per wound).
# ---------------------------------------------------------------------------
def get_wound_lock(request: Request, wound_id: str) -> threading.Lock:
    """Return the process-wide lock for ``wound_id`` (created on first use)."""
    registry: dict[str, threading.Lock] = request.app.state.wound_locks
    guard: threading.Lock = request.app.state.wound_locks_guard
    with guard:
        return registry[wound_id]


def make_lock_registry() -> defaultdict[str, threading.Lock]:
    return defaultdict(threading.Lock)
