from datetime import datetime, timezone
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import get_session
from backend.models import ReadingRecord
from backend.safety import evaluate_safety
from backend.schemas import (
    ReadingCreate,
    ReadingStatus,
    ReadingView,
    ScenarioRequest,
)
from backend.simulator import scenario_payload

router = APIRouter()


def _serialize_status(record: ReadingRecord | None) -> ReadingStatus:
    if record is None:
        return ReadingStatus(
            status="keep_watching",
            reason_code="no_reading_yet",
            needs_clinician=False,
            metric_status={
                "ph": "check",
                "temperature": "check",
                "moisture": "check",
            },
            reading=None,
        )

    safety = {
        "status": record.status,
        "reason_code": record.reason_code,
        "needs_clinician": record.status == "see_doctor_today",
        "metric_status": evaluate_safety(
            {
                "ph": record.ph,
                "skin_temp_c": record.skin_temp_c,
                "moisture_pct": record.moisture_pct,
                "sensor_status": record.sensor_status,
            },
            record.clinical_context,
        )["metric_status"],
    }
    reading = ReadingView(
        id=record.id,
        device_id=record.device_id,
        wound_id=record.wound_id,
        ts=record.ts,
        ph=record.ph,
        skin_temp_c=record.skin_temp_c,
        moisture_pct=record.moisture_pct,
        battery_pct=record.battery_pct,
        sensor_status=record.sensor_status,
    )
    return ReadingStatus(**safety, reading=reading)


def _latest(session: Session) -> ReadingRecord | None:
    return session.scalar(
        select(ReadingRecord).order_by(
            ReadingRecord.ts.desc(), ReadingRecord.id.desc()
        ).limit(1)
    )


@router.get("/healthz")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/readings", response_model=ReadingStatus, status_code=status.HTTP_201_CREATED)
def create_reading(
    body: ReadingCreate, session: Session = Depends(get_session)
) -> ReadingStatus:
    duplicate = session.scalar(
        select(ReadingRecord.id).where(
            ReadingRecord.device_id == body.device_id,
            ReadingRecord.ts == body.ts,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Duplicate device reading")

    payload = body.model_dump()
    context = payload.pop("clinical_context")
    safety = evaluate_safety(payload, context)
    record = ReadingRecord(
        **payload,
        clinical_context=context,
        status=safety["status"],
        reason_code=safety["reason_code"],
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate device reading") from error
    session.refresh(record)
    return _serialize_status(record)


@router.get("/readings/latest", response_model=ReadingStatus)
def get_latest_reading(session: Session = Depends(get_session)) -> ReadingStatus:
    return _serialize_status(_latest(session))


@router.get("/status", response_model=ReadingStatus)
def get_status(session: Session = Depends(get_session)) -> ReadingStatus:
    return _serialize_status(_latest(session))


@router.post("/simulator/scenario", response_model=ReadingStatus)
async def set_simulator_scenario(body: ScenarioRequest) -> ReadingStatus:
    payload = scenario_payload(body)
    port = int(os.getenv("PORT", "8080"))
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/api/readings", json=payload
            )
            response.raise_for_status()
            return ReadingStatus.model_validate(response.json())
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=503, detail="The simulator could not record a reading."
        ) from error


async def simulator_loop() -> None:
    """Keep generating demo readings through the same ingestion endpoint."""
    import asyncio
    import logging
    logger = logging.getLogger("sushruta.simulator")
    port = int(os.getenv("PORT", "8080"))
    await asyncio.sleep(1)
    async with httpx.AsyncClient(timeout=8.0) as client:
        while True:
            try:
                await client.post(
                    f"http://127.0.0.1:{port}/api/readings",
                    json=scenario_payload(
                        ScenarioRequest(scenario="healing")
                    ),
                )
            except httpx.HTTPError:
                logger.warning("Simulator could not post a reading; will retry.")
            await asyncio.sleep(60)
