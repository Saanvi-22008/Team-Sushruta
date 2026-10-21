import asyncio
import os

from fastapi import APIRouter, Query

from backend import apollo, llm, store
from backend.safety import classify_metrics
from backend.schemas import ApolloReply, ApolloRequest, TinyFishActivity

router = APIRouter()


def _wound_state() -> dict[str, str] | None:
    """Current status in categories only (no names, no raw values)."""
    try:
        record = store.latest_reading()
    except Exception:  # noqa: BLE001 - Apollo still works without readings
        return None
    if record is None:
        return None
    metrics = classify_metrics(
        {"ph": record.ph, "skin_temp_c": record.skin_temp_c, "moisture_pct": record.moisture_pct}
    )
    return {
        "status": record.status,
        "ph": metrics["ph"],
        "temperature": metrics["temperature"],
        "moisture": metrics["moisture"],
    }


@router.post("/apollo/chat", response_model=ApolloReply)
async def apollo_chat(body: ApolloRequest) -> dict:
    state = await asyncio.to_thread(_wound_state)
    return await apollo.answer(body.message.strip(), body.language, state)


@router.get("/tinyfish/activity", response_model=list[TinyFishActivity])
async def tinyfish_activity(limit: int = Query(20, ge=1, le=50)) -> list[dict]:
    try:
        return await asyncio.to_thread(store.recent_calls, limit)
    except Exception:  # noqa: BLE001
        return []


@router.get("/apollo/health")
def apollo_health() -> dict[str, object]:
    """Which secrets are configured. Never returns the secrets themselves."""
    return {
        "tinyfish_key": bool(os.getenv("TINYFISH_API_KEY")),
        "gemini_key": llm.configured(),
        "gemini_model": llm.model_name(),
        "sarvam_key": bool(os.getenv("SARVAM_API_KEY")),
        "trusted_domains": apollo.TRUSTED_DOMAINS,
    }
