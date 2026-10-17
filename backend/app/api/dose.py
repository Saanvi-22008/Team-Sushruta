"""Light-dose request endpoint: POST /wounds/{wound_id}/dose-requests.

The decision runs under a PER-WOUND lock inside a DB transaction so a racing
request for the same wound evaluates the caps against the committed grant record
(invariant #6). The server enforces the hard caps from config only; the request
body supplies just the two requested parameters.

- 201 on grant  -> ``granted_params`` + ``next_allowed_at``.
- 409 on deny   -> ``enforced_limits`` + machine-readable ``reason_code`` + reason.
- 503 when the safety config is in fail-safe.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import service
from app.api.deps import get_session, get_wound_lock, require_config, utcnow
from app.core.config import SafetyConfig
from app.core.models_db import AuditLog, DoseRequest
from app.core.schemas import DoseDenied, DoseGranted, DoseRequestIn
from app.safety import dose
from app.safety.dose import OUTCOME_GRANTED

router = APIRouter(tags=["dose"])


def _committed_grants(session: Session, wound_id: str) -> list[DoseRequest]:
    """Load this wound's GRANTED dose requests (the committed grant record)."""
    return (
        session.execute(
            select(DoseRequest)
            .where(DoseRequest.wound_id == wound_id)
            .where(DoseRequest.outcome == OUTCOME_GRANTED)
            .order_by(DoseRequest.requested_at)
        )
        .scalars()
        .all()
    )


@router.post("/wounds/{wound_id}/dose-requests", response_model=None)
def request_dose(
    wound_id: str,
    body: DoseRequestIn,
    response: Response,
    session: Session = Depends(get_session),
    config: SafetyConfig = Depends(require_config),
    lock=Depends(get_wound_lock),
):
    """Request a light session; caps are enforced server-side, deny-closed."""
    now = utcnow()

    # Serialise per wound so concurrent requests cannot beat the gap/daily caps:
    # each one reads the grants already committed by the one before it.
    with lock:
        grants = _committed_grants(session, wound_id)
        current = service.compute_status(session, wound_id, config, now)
        decision = dose.decide(wound_id, body, grants, current, config, now)

        record = DoseRequest(
            wound_id=wound_id,
            requested_at=now,
            requested_params={
                "requested_dose_mj": body.requested_dose_mj,
                "requested_duration_s": body.requested_duration_s,
            },
            outcome=decision.outcome,
            enforced_limits=decision.enforced_limits,
            reason=decision.reason,
            granted_params=decision.granted_params,
            config_snapshot=config.config_snapshot,
        )
        session.add(record)
        session.flush()
        session.add(
            AuditLog(
                ts=now,
                kind="dose",
                wound_id=wound_id,
                payload={
                    "dose_request_id": record.id,
                    "outcome": decision.outcome,
                    "reason_code": decision.reason_code,
                    "reason": decision.reason,
                    "requested_params": record.requested_params,
                    "granted_params": decision.granted_params,
                    "enforced_limits": decision.enforced_limits,
                    "config_snapshot": config.config_snapshot,
                },
            )
        )
        session.commit()

    if decision.granted:
        response.status_code = status.HTTP_201_CREATED
        return DoseGranted(
            outcome=decision.outcome,
            granted_params=decision.granted_params or {},
            next_allowed_at=decision.next_allowed_at,
            enforced_limits=decision.enforced_limits,
            reason=decision.reason,
        )

    # Denied. A config fail-safe maps to 503; every other denial is a 409.
    if decision.config_failsafe:
        raise HTTPException(status_code=503, detail=decision.reason)

    response.status_code = status.HTTP_409_CONFLICT
    return DoseDenied(
        outcome=decision.outcome,
        reason_code=decision.reason_code or "denied",
        reason=decision.reason,
        enforced_limits=decision.enforced_limits,
        next_allowed_at=decision.next_allowed_at,
    )
