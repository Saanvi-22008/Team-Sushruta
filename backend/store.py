"""Small database helpers for the TinyFish activity log and guidance cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import GuidanceCache, ReadingRecord, TinyFishCall


def log_call(
    *,
    kind: str,
    topic: str,
    query_text: str,
    status: str,
    detail: str = "",
    result_count: int = 0,
    elapsed_ms: int = 0,
) -> None:
    with SessionLocal() as session:
        session.add(
            TinyFishCall(
                kind=kind,
                topic=topic[:48],
                query_text=query_text[:300],
                status=status[:24],
                detail=detail[:200],
                result_count=result_count,
                elapsed_ms=elapsed_ms,
            )
        )
        session.commit()


def recent_calls(limit: int = 20) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(TinyFishCall).order_by(TinyFishCall.id.desc()).limit(limit)
        ).all()
        return [
            {
                "ts": row.ts,
                "kind": row.kind,
                "topic": row.topic,
                "query": row.query_text,
                "status": row.status,
                "detail": row.detail,
                "result_count": row.result_count,
                "elapsed_ms": row.elapsed_ms,
            }
            for row in rows
        ]


def get_cache(topic: str) -> tuple[list[dict[str, Any]], datetime] | None:
    with SessionLocal() as session:
        row = session.get(GuidanceCache, topic)
        if row is None:
            return None
        created = row.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return list(row.sources), created


def put_cache(topic: str, sources: list[dict[str, Any]]) -> None:
    with SessionLocal() as session:
        row = session.get(GuidanceCache, topic)
        now = datetime.now(timezone.utc)
        if row is None:
            session.add(GuidanceCache(topic=topic, sources=sources, created_at=now))
        else:
            row.sources = sources
            row.created_at = now
        session.commit()


def is_fresh(created_at: datetime, hours: float = 6.0) -> bool:
    return datetime.now(timezone.utc) - created_at < timedelta(hours=hours)


def latest_reading() -> ReadingRecord | None:
    with SessionLocal() as session:
        return session.scalar(
            select(ReadingRecord)
            .order_by(ReadingRecord.ts.desc(), ReadingRecord.id.desc())
            .limit(1)
        )
