"""Pydantic v2 wire-contract schemas for the Sushruta safety core.

Every input schema sets ``extra='forbid'`` (OpenAPI ``additionalProperties: false``)
so a caller can never inject a threshold, cap, or forced status (safety invariant
#7 / Req 14). The engine and dose enforcement read limits ONLY from config, never
from these request bodies.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SensorStatus(str, Enum):
    """Allowed sensor_status values on the wire.

    Any value outside this set is normalized to ``disconnected`` by the domain
    validator (with a warning) — it is never trusted as-is.
    """

    ok = "ok"
    drifting = "drifting"
    disconnected = "disconnected"


class ReadingIn(BaseModel):
    """Strict ingestion contract for one bandage reading.

    Unknown fields are rejected (``extra='forbid'``). ``sensor_status`` is typed
    as the enum here; the raw wire value is additionally normalized/flagged by
    the domain validator so an out-of-enum string can be downgraded rather than
    hard-rejected when ingestion needs to stay resilient.
    """

    model_config = ConfigDict(extra="forbid")

    device_id: str
    wound_id: str
    ts: datetime
    ph: float
    skin_temp_c: float
    moisture_pct: float
    battery_pct: float
    sensor_status: SensorStatus


class TrendOut(BaseModel):
    """Per-metric trend direction plus the overall trend computation status."""

    model_config = ConfigDict(extra="forbid")

    ph: str
    temp: str
    status: str  # ok | insufficient_data


class StatusOut(BaseModel):
    """Deterministic wound status result returned by the status endpoints."""

    model_config = ConfigDict(extra="forbid")

    wound_id: str
    level: str  # normal | watch | infection-risk | escalate
    machine_code: Optional[str] = None
    data_level: str  # data-driven level, may be "unknown"
    red_flags: list[str] = []
    sensor_health: str  # ok | drifting | disconnected
    stale: bool
    simulated: bool
    trend: TrendOut
    confidence: str  # normal | reduced
    reason: str
    last_updated: Optional[datetime] = None
    config_snapshot: Optional[str] = None


class DoseRequestIn(BaseModel):
    """REQUEST a 405nm light session. Allow-list only; caps live in config.

    Only the two request parameters are accepted; no cap/threshold/override
    field is honored (``extra='forbid'``).
    """

    model_config = ConfigDict(extra="forbid")

    requested_dose_mj: float
    requested_duration_s: float
