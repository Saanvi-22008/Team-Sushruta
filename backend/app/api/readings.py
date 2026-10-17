"""Ingestion endpoints: POST /readings and POST /readings/batch.

Ingest flow (design.md): validate -> persist reading -> load recent history +
wound attrs + symptoms -> evaluate (FEAT-003 engine) -> persist status -> audit
-> return 201 ``{reading_id, status}``.

Fail-safe behaviour:
- Safety config in fail-safe => 503 (we cannot compute a trustworthy status).
- Duplicate (same device/wound/ts) => 409 idempotent no-op.
- Contract violation (missing/wrong-type field) => 422.
- Datastore unavailable => 5xx, NEVER a success.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import service
from app.api.deps import get_session, require_config, utcnow
from app.core.config import SafetyConfig
from app.core.models_db import Reading
from app.core.schemas import BatchItemResult, ReadingAccepted, ReadingIn
from app.ingestion.validator import ContractError, ValidatedReading, validate_reading
from app.safety import audit

router = APIRouter(tags=["readings"])


def _persist_reading(session: Session, vr: ValidatedReading) -> Reading:
    """Insert a validated reading. Caller owns commit; may raise IntegrityError."""
    row = Reading(
        device_id=vr.device_id,
        wound_id=vr.wound_id,
        ts=vr.ts,
        ph=vr.ph,
        skin_temp_c=vr.skin_temp_c,
        moisture_pct=vr.moisture_pct,
        battery_pct=vr.battery_pct,
        sensor_status=vr.sensor_status,
        source=vr.source,
        simulated=vr.simulated,
        field_flags=vr.field_flags,
        dedup_key=vr.dedup_key,
    )
    session.add(row)
    session.flush()  # assign PK + surface a UNIQUE(dedup_key) violation now
    return row


def _ingest_one(
    session: Session,
    payload: dict[str, Any],
    config: SafetyConfig,
) -> ReadingAccepted:
    """Validate+persist one reading and compute/persist/audit its status.

    Runs inside the caller's transaction so the reading, its status, and the
    audit row land atomically. Raises ContractError (-> 422), IntegrityError
    (duplicate -> 409) or SQLAlchemyError (datastore -> 5xx).
    """
    now = utcnow()
    vr = validate_reading(
        payload,
        config.clinical,
        source="http",
        simulated=bool(payload.get("simulated", False)),
        now=now,
    )
    reading = _persist_reading(session, vr)

    result = service.compute_status(session, vr.wound_id, config, now)
    audit.persist_status(
        session,
        result,
        config_snapshot=config.config_snapshot,
        from_reading_id=reading.id,
        computed_at=now,
    )
    return ReadingAccepted(reading_id=reading.id, status=service.to_status_out(result))


@router.post("/readings", status_code=status.HTTP_201_CREATED, response_model=ReadingAccepted)
def ingest_reading(
    reading: ReadingIn,
    session: Session = Depends(get_session),
    config: SafetyConfig = Depends(require_config),
) -> ReadingAccepted:
    payload = reading.model_dump(mode="json")
    try:
        accepted = _ingest_one(session, payload, config)
        session.commit()
        return accepted
    except ContractError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail={"fields": exc.fields, "message": str(exc)})
    except IntegrityError:
        # Duplicate dedup_key -> idempotent no-op.
        session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate reading (same device/wound/ts).")
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=f"Datastore unavailable: {exc}")


@router.post("/readings/batch", status_code=status.HTTP_207_MULTI_STATUS)
def ingest_batch(
    items: list[dict],
    response: Response,
    session: Session = Depends(get_session),
    config: SafetyConfig = Depends(require_config),
) -> list[BatchItemResult]:
    """Ingest many readings, returning a per-item result (207 Multi-Status).

    The body is accepted as raw objects (not ``list[ReadingIn]``) so a single
    malformed item is reported per-item as ``invalid`` instead of failing the
    whole request with a 422. Each item is validated with the SAME strict
    contract (``ReadingIn`` extra='forbid') before ingestion.
    """
    results: list[BatchItemResult] = []
    for index, raw in enumerate(items):
        try:
            reading = ReadingIn.model_validate(raw)
        except ValidationError as exc:
            fields = sorted({str(e["loc"][-1]) for e in exc.errors()})
            results.append(BatchItemResult(index=index, outcome="invalid", errors=fields))
            continue

        payload = reading.model_dump(mode="json")
        try:
            accepted = _ingest_one(session, payload, config)
            session.commit()
            results.append(
                BatchItemResult(
                    index=index,
                    outcome="stored",
                    reading_id=accepted.reading_id,
                    status=accepted.status,
                )
            )
        except ContractError as exc:
            session.rollback()
            results.append(
                BatchItemResult(index=index, outcome="invalid", errors=exc.fields)
            )
        except IntegrityError:
            session.rollback()
            results.append(BatchItemResult(index=index, outcome="duplicate"))
        except SQLAlchemyError as exc:
            session.rollback()
            results.append(
                BatchItemResult(index=index, outcome="invalid", errors=[f"datastore: {exc}"])
            )
    response.status_code = status.HTTP_207_MULTI_STATUS
    return results
