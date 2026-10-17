"""Status + timeline endpoints.

- ``GET /wounds/{wound_id}/status``   -> the current deterministic StatusOut
  (recomputed from stored readings so it always reflects the latest config).
- ``GET /wounds/{wound_id}/timeline`` -> ts-ordered readings + statuses with
  optional ``from`` / ``to`` / ``limit`` query params.

Both refuse (503) when the safety config is in fail-safe, and 404 for an unknown
wound (no readings and no status history).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import service
from app.api.deps import get_session, require_config, utcnow
from app.core.config import SafetyConfig
from app.core.models_db import Reading, Status
from app.core.schemas import StatusOut

router = APIRouter(tags=["status"])


def _wound_exists(session: Session, wound_id: str) -> bool:
    has_reading = session.execute(
        select(Reading.id).where(Reading.wound_id == wound_id).limit(1)
    ).first()
    if has_reading:
        return True
    has_status = session.execute(
        select(Status.id).where(Status.wound_id == wound_id).limit(1)
    ).first()
    return bool(has_status)


@router.get("/wounds/{wound_id}/status", response_model=StatusOut)
def get_status(
    wound_id: str,
    session: Session = Depends(get_session),
    config: SafetyConfig = Depends(require_config),
) -> StatusOut:
    if not _wound_exists(session, wound_id):
        raise HTTPException(status_code=404, detail=f"Unknown wound '{wound_id}'.")
    result = service.compute_status(session, wound_id, config, utcnow())
    return service.to_status_out(result)


@router.get("/wounds/{wound_id}/timeline")
def get_timeline(
    wound_id: str,
    session: Session = Depends(get_session),
    config: SafetyConfig = Depends(require_config),
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to: Optional[datetime] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Return ts-ordered readings + statuses for ``wound_id``."""
    if not _wound_exists(session, wound_id):
        raise HTTPException(status_code=404, detail=f"Unknown wound '{wound_id}'.")

    reading_q = select(Reading).where(Reading.wound_id == wound_id)
    status_q = select(Status).where(Status.wound_id == wound_id)
    if from_ is not None:
        reading_q = reading_q.where(Reading.ts >= from_)
        status_q = status_q.where(Status.computed_at >= from_)
    if to is not None:
        reading_q = reading_q.where(Reading.ts <= to)
        status_q = status_q.where(Status.computed_at <= to)

    reading_rows = (
        session.execute(reading_q.order_by(Reading.ts).limit(limit)).scalars().all()
    )
    status_rows = (
        session.execute(status_q.order_by(Status.computed_at).limit(limit)).scalars().all()
    )

    readings = [
        {
            "reading_id": r.id,
            "ts": r.ts,
            "ph": r.ph,
            "skin_temp_c": r.skin_temp_c,
            "moisture_pct": r.moisture_pct,
            "battery_pct": r.battery_pct,
            "sensor_status": r.sensor_status,
            "simulated": bool(r.simulated),
            "field_flags": r.field_flags,
        }
        for r in reading_rows
    ]
    statuses = [
        {
            "status_id": s.id,
            "ts": s.computed_at,
            "level": s.level,
            "machine_code": s.machine_code,
            "data_level": s.data_level,
            "sensor_health": s.sensor_health,
            "stale": s.stale,
            "reason": s.reason_text,
            "from_reading_id": s.from_reading_id,
        }
        for s in status_rows
    ]
    return {"wound_id": wound_id, "readings": readings, "statuses": statuses}
