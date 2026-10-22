import asyncio
import os

from fastapi import APIRouter, HTTPException, Query

from backend import apollo, care_finder, store, tinyfish
from backend.safety import classify_metrics
from backend.schemas import ApolloReply, ApolloRequest, CareReply, CareRequest, TinyFishActivity

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


_CARE_HTTP = {
    "no_key": 503, "auth": 503, "out_of_credits": 503, "rate_limited": 429,
    "timeout": 504, "no_results": 404,
}


@router.post("/apollo/find-care", response_model=CareReply)
async def find_care(body: CareRequest) -> dict:
    """A TinyFish browser agent looks up clinics near the area the user typed."""
    try:
        return await care_finder.find_care(body.area)
    except care_finder.AreaError as error:
        raise HTTPException(status_code=422, detail={"code": "bad_area", "message": str(error)}) from error
    except tinyfish.TinyFishError as error:
        raise HTTPException(
            status_code=_CARE_HTTP.get(error.code, 502), detail={"code": error.code}
        ) from error


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
        "sarvam_key": bool(os.getenv("SARVAM_API_KEY")),
        "trusted_domains": apollo.TRUSTED_DOMAINS,
    }
