"""Persist a status decision so it is reproducible from stored data.

``persist_status(session, result, *, config_snapshot, from_reading_id)`` writes
two rows inside the caller's transaction:

- a ``statuses`` row — the decision (level, machine_code, data_level,
  sensor_health, stale, factors, reason, config_snapshot, from_reading_id);
- an ``audit_log`` row (kind ``status``) carrying the full factor payload.

Reproducibility: the stored ``config_snapshot`` plus the ``readings`` the
decision was computed from (and ``from_reading_id`` for the latest) let an
auditor re-run :func:`app.safety.rules.evaluate` and obtain the same result —
the engine is pure, so stored readings + the same config reproduce the decision.

This module performs NO network, LLM, or ML call; it only writes to the DB
session it is handed (the session/transaction is owned by the caller).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.models_db import AuditLog, Status
from app.safety.rules import StatusResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def status_to_factors(result: StatusResult) -> dict:
    """Build the JSON factor payload recorded on the status + audit rows."""
    return {
        "level": result.level,
        "machine_code": result.machine_code,
        "data_level": result.data_level,
        "red_flags": list(result.red_flags),
        "red_flags_from_unknown": [
            f.code for f in result.red_flag_details if f.from_unknown
        ],
        "sensor_health": result.sensor_health,
        "stale": result.stale,
        "simulated": result.simulated,
        "confidence": result.confidence,
        "trend": result.trend,
        "reason": result.reason,
        "detail": result.factors,
    }


def persist_status(
    session: Session,
    result: StatusResult,
    *,
    wound_id: Optional[str] = None,
    config_snapshot: Optional[str] = None,
    from_reading_id: Optional[int] = None,
    computed_at: Optional[datetime] = None,
) -> Status:
    """Persist ``result`` as a ``statuses`` row + an ``audit_log`` entry.

    The write happens on the caller's ``session`` (the caller owns commit/rollback
    so the status + audit rows land atomically with any surrounding work).
    Returns the created :class:`~app.core.models_db.Status`.
    """
    wid = wound_id or result.wound_id
    if wid is None:
        raise ValueError("wound_id is required to persist a status decision")

    snapshot = config_snapshot if config_snapshot is not None else result.config_snapshot
    factors = status_to_factors(result)
    when = computed_at or _utcnow()

    status = Status(
        wound_id=wid,
        computed_at=when,
        from_reading_id=from_reading_id,
        level=result.level,
        machine_code=result.machine_code,
        data_level=result.data_level,
        sensor_health=result.sensor_health,
        stale=result.stale,
        factors=factors,
        reason_text=result.reason,
        config_snapshot=snapshot,
    )
    session.add(status)

    audit = AuditLog(
        ts=when,
        kind="status",
        wound_id=wid,
        payload={
            "machine_code": result.machine_code,
            "level": result.level,
            "from_reading_id": from_reading_id,
            "config_snapshot": snapshot,
            "factors": factors,
        },
    )
    session.add(audit)
    session.flush()  # assign PKs without committing (caller owns the transaction)
    return status
