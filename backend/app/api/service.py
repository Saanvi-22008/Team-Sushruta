"""Shared service helpers that bridge persisted rows and the pure safety core.

Both the ingestion and status endpoints need to load a wound's reading history,
gather its attributes + reported symptoms, run the deterministic engine, and map
the result onto the :class:`~app.core.schemas.StatusOut` wire shape. That logic
lives here so it is identical on every path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ReadingAdapter
from app.core.config import SafetyConfig
from app.core.models_db import ReportedSymptom, Reading, Wound
from app.core.schemas import StatusOut, TrendOut
from app.safety import rules
from app.safety.rules import StatusResult


def load_history(session: Session, wound_id: str) -> list[ReadingAdapter]:
    """Return every stored reading for ``wound_id`` as engine-ready adapters."""
    rows = (
        session.execute(
            select(Reading).where(Reading.wound_id == wound_id).order_by(Reading.ts)
        )
        .scalars()
        .all()
    )
    return [ReadingAdapter(r) for r in rows]


def _latest_symptoms(session: Session, wound_id: str) -> dict[str, bool]:
    """Collapse reported symptoms to {kind: present} using the most recent row.

    A missing symptom stays absent (unknown), never invented as False/True.
    """
    rows = (
        session.execute(
            select(ReportedSymptom)
            .where(ReportedSymptom.wound_id == wound_id)
            .order_by(ReportedSymptom.ts)
        )
        .scalars()
        .all()
    )
    symptoms: dict[str, bool] = {}
    for r in rows:  # ordered ascending => later rows win
        symptoms[r.kind] = bool(r.present)
    return symptoms


def _wound_attrs(session: Session, wound_id: str) -> dict[str, object]:
    """Gather wound attributes; None/missing stays unknown (never defaulted)."""
    wound: Optional[Wound] = session.get(Wound, wound_id)
    if wound is None:
        return {}
    return {
        "attr_diabetic": wound.attr_diabetic,
        "attr_immunocompromised": wound.attr_immunocompromised,
        "depth_type": wound.depth_type,
    }


def compute_status(
    session: Session,
    wound_id: str,
    config: SafetyConfig,
    now: datetime,
) -> StatusResult:
    """Run the pure engine for ``wound_id`` from its persisted state."""
    history = load_history(session, wound_id)
    attrs = _wound_attrs(session, wound_id)
    symptoms = _latest_symptoms(session, wound_id)
    return rules.evaluate(
        history,
        attrs,
        now,
        config,
        symptoms=symptoms,
        config_snapshot=config.config_snapshot,
        wound_id=wound_id,
    )


def to_status_out(result: StatusResult) -> StatusOut:
    """Map a :class:`StatusResult` onto the wire schema."""
    return StatusOut(
        wound_id=result.wound_id,
        level=result.level,
        machine_code=result.machine_code,
        data_level=result.data_level,
        red_flags=list(result.red_flags),
        sensor_health=result.sensor_health,
        stale=result.stale,
        simulated=result.simulated,
        trend=TrendOut(
            ph=result.trend["ph"],
            temp=result.trend["temp"],
            status=result.trend["status"],
        ),
        confidence=result.confidence,
        reason=result.reason,
        last_updated=result.last_updated,
        config_snapshot=result.config_snapshot,
    )
