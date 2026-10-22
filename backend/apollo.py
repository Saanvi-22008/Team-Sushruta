"""Apollo: answers wound-care questions only from trusted, cited sources.

Safety order (never reversed):
1. Deterministic red-flag and status checks decide whether to escalate. TinyFish
   content can never turn an escalation off.
2. TinyFish supplies live guidance from an allow-list of health sites.
3. The answer is built only from sentences taken from those pages, chosen by
   how well they match the question (computed here, nothing is sent out) and
   cited. No language model writes or rewords anything.
4. If TinyFish is unavailable, saved notes are used and clearly labelled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend import store, tinyfish

logger = logging.getLogger("sushruta.apollo")

ROOT = Path(__file__).resolve().parents[1]
PURPOSE = "Find trusted public patient information on a wound-care topic for an educational app"
CACHE_HOURS = 6.0


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


TRUSTED_DOMAINS: list[str] = _load(ROOT / "config" / "trusted_domains.json")["domains"]
KNOWLEDGE: dict[str, Any] = _load(ROOT / "knowledge" / "topics.json")

# ---------------------------------------------------------------------------
# Pre-written strings. These are never machine-generated at runtime.
# ---------------------------------------------------------------------------
ESCALATION = {
    "en": (
        "What you describe can be a warning sign. Please speak with a clinician today. "
        "If you feel very unwell or it is severe, call emergency services."
    ),
    "hi": (
        "आपने जो बताया वह चेतावनी का संकेत हो सकता है। कृपया आज ही डॉक्टर से बात करें। "
        "अगर आप बहुत बीमार महसूस करें या स्थिति गंभीर हो, तो आपातकालीन सेवा को कॉल करें।"
    ),
}
NOT_SURE = {
    "en": "I'm not sure about this from the sources I have. Please consult a doctor.",
    "hi": "मेरे पास मौजूद स्रोतों से मैं इस बारे में निश्चित नहीं हूँ। कृपया डॉक्टर से सलाह लें।",
}
LEAD_LIVE = {
    "en": "Here is what trusted health sites say about this:",
    "hi": "भरोसेमंद स्वास्थ्य वेबसाइटों में यह जानकारी मिली (अंग्रेज़ी में):",
}
LEAD_OFFLINE = {
    "en": "I couldn't reach live guidance, so this comes from the team's saved notes:",
    "hi": "लाइव जानकारी नहीं मिल सकी, इसलिए यह टीम के सहेजे हुए नोट्स से है:",
}

# ---------------------------------------------------------------------------
# Topics. The text sent to TinyFish is ONLY the fixed `query` below, so no
# patient data can leave the server. English keywords are regexes; Hindi are plain.
# ---------------------------------------------------------------------------
TOPICS: list[dict[str, Any]] = [
    {
        "id": "infection_signs",
        "query": "signs of wound infection when to see a doctor",
        "en": [r"infect", r"\bpus\b", r"discharge", r"swell", r"swollen", r"\bred(ness)?\b", r"\bsmell"],
        "hi": ["मवाद", "संक्रमण", "सूजन", "लाल", "बदबू"],
    },
    {
        "id": "ph",
        "query": "wound pH alkaline chronic wound infection healing",
        "en": [r"\bph\b", r"alkalin", r"\bacid"],
        "hi": ["अम्ल", "क्षार", "पीएच"],
    },
    {
        "id": "moisture_dressing",
        "query": "how to change a wound dressing keep wound clean and dry",
        "en": [r"moist", r"\bwet\b", r"soak", r"dressing", r"bandage", r"\bchange\b"],
        "hi": ["नमी", "गीला", "पट्टी", "बदल"],
    },
    {
        "id": "temperature",
        "query": "warm skin around a wound infection signs",
        "en": [r"\bwarm", r"temperature", r"\bhot\b", r"\bheat"],
        "hi": ["गर्म", "तापमान", "गर्माहट"],
    },
    {
        "id": "pain",
        "query": "wound pain getting worse when to see a doctor",
        "en": [r"\bpain", r"\bhurt", r"\bsore\b", r"throb"],
        "hi": ["दर्द"],
    },
    {
        "id": "healing",
        "query": "how wounds heal stages and how long it takes",
        "en": [r"\bheal", r"how long", r"scab", r"\bscar", r"itch"],
        "hi": ["भर", "ठीक", "खुजली", "निशान"],
    },
    {
        "id": "bleeding",
        "query": "how to stop bleeding from a minor cut",
        "en": [r"bleed", r"\bblood"],
        "hi": ["खून", "रक्त"],
    },
    {
        "id": "diabetes",
        "query": "diabetes wound care foot wounds when to see a doctor",
        "en": [r"diabet", r"\bsugar\b"],
        "hi": ["मधुमेह", "डायबिटीज", "शुगर"],
    },
]
GENERAL_TOPIC: dict[str, Any] = {
    "id": "general",
    "query": "how to care for a cut or wound and when to get medical help",
    "en": [],
    "hi": [],
}
GENERIC_PATTERNS = [r"infect", r"doctor|clinician|provider|nurse", r"pus|redness|swell|fever|pain", r"call|contact|seek"]

# Red flags are checked with plain rules. They only ever ADD an escalation.
RED_FLAG_PATTERNS: dict[str, list[str]] = {
    "pus": [r"\bpus\b", r"discharge", "मवाद"],
    "spreading_redness": [r"\bspreading\b", r"red streak", r"redness (is )?spread", "फैल"],
    "fever": [r"\bfever\b", r"\bchills\b", "बुखार"],
    "severe_pain": [r"severe pain", r"unbearable", r"very painful", r"pain (is )?(getting )?worse", "तेज़ दर्द", "तेज दर्द", "बहुत दर्द"],
    "bad_smell": [r"bad smell", r"foul", r"\bsmells?\b", "बदबू"],
    "bite_or_puncture": [r"\bbite\b", r"\bbitten\b", r"puncture", r"\brusty\b", "कुत्ते", "काटा"],
    "deep_or_gaping": [r"\bdeep\b", r"gaping", r"\bbone\b", "गहरा"],
    "bleeding_wont_stop": [r"won'?t stop bleeding", r"not stop(ping)? bleeding", r"heavy bleeding", "खून नहीं रुक"],
    "black_tissue": [r"black (skin|edge|tissue)", "काली त्वचा"],
}
_NEGATION_BEFORE = re.compile(r"\b(no|not|without|never|isn'?t|doesn'?t|don'?t|hasn'?t|haven'?t)\b")


def _normalise(text: str) -> str:
    return text.replace("’", "'").lower()


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def pick_topic(message: str) -> dict[str, Any]:
    """Choose a fixed topic by keyword. Ties go to the earlier topic."""
    text = _normalise(message)
    best: dict[str, Any] = GENERAL_TOPIC
    best_score = 0
    for topic in TOPICS:
        score = sum(1 for p in _compile(topic["en"]) if p.search(text))
        score += sum(1 for word in topic["hi"] if word in text)
        if score > best_score:
            best, best_score = topic, score
    return best


def detect_red_flags(message: str) -> list[str]:
    """Return the red flags named in the message, ignoring simple negations."""
    text = _normalise(message)
    found: list[str] = []
    for name, patterns in RED_FLAG_PATTERNS.items():
        for pattern in _compile(patterns):
            for match in pattern.finditer(text):
                before = text[max(0, match.start() - 14) : match.start()]
                after = text[match.end() : match.end() + 14]
                if _NEGATION_BEFORE.search(before) or "नहीं" in after or "नही" in after:
                    continue
                found.append(name)
                break
            if name in found:
                break
    return found


# ---------------------------------------------------------------------------
# Source handling
# ---------------------------------------------------------------------------
def condense(text: str, patterns: list[re.Pattern[str]], limit: int = 3000) -> str:
    """Keep the paragraphs most relevant to the topic, in their original order."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return text[:limit]
    scored = [(sum(1 for p in patterns if p.search(par)), i, par) for i, par in enumerate(paragraphs)]
    chosen: set[int] = set()
    total = 0
    for score, index, par in sorted(scored, key=lambda item: (-item[0], item[1])):
        if score == 0 and chosen:
            continue
        if total + len(par) > limit:
            continue
        chosen.add(index)
        total += len(par)
    if not chosen:
        return paragraphs[0][:limit]
    return "\n\n".join(paragraphs[i] for i in sorted(chosen))


def best_excerpt(text: str, patterns: list[re.Pattern[str]], limit: int = 380) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return ""
    best = max(paragraphs, key=lambda par: sum(1 for p in patterns if p.search(par)) * 1000 + min(len(par), 200))
    clean = re.sub(r"^[#*\-\s]+", "", best, flags=re.MULTILINE)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > limit:
        clean = clean[:limit].rsplit(" ", 1)[0] + "…"
    return clean


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def offline_sources(topic: dict[str, Any], language: str) -> list[dict[str, Any]]:
    topics = KNOWLEDGE["topics"]
    entry = topics.get(topic["id"]) or topics["general"]
    return [
        {
            "n": 1,
            "title": entry["title"][language],
            "url": None,
            "domain": KNOWLEDGE["label"][language],
            "text": entry[language],
            "snippet": entry[language][:200],
            "retrieved_at": None,
            "origin": "offline",
        }
    ]


def _number(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, source in enumerate(sources, start=1):
        source["n"] = index
    return sources


async def _db(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a blocking database helper. A database problem must never stop Apollo."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except Exception:  # noqa: BLE001 - guidance must keep working without the DB
        logger.warning("Database helper %s failed", getattr(fn, "__name__", "?"), exc_info=True)
        return None


async def _live_sources(topic: dict[str, Any], record: Any) -> list[dict[str, Any]]:
    patterns = _compile(topic["en"] + GENERIC_PATTERNS)
    started = time.monotonic()
    results = await tinyfish.search(
        topic["query"], purpose=PURPOSE, include_domains=TRUSTED_DOMAINS, language="en"
    )
    await record("search", "ok", "", len(results), started)

    chosen: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in results:
        url = item["url"]
        if url in seen or url.lower().endswith(".pdf"):
            continue
        if not tinyfish.host_allowed(url, TRUSTED_DOMAINS):
            continue
        seen.add(url)
        chosen.append(item)
        if len(chosen) == 3:
            break
    if not chosen:
        raise tinyfish.TinyFishError("no_results", "no allow-listed results")

    started = time.monotonic()
    pages: dict[str, dict[str, Any]] = {}
    try:
        fetched, errors = await tinyfish.fetch([c["url"] for c in chosen], purpose=PURPOSE)
        for page in fetched:
            for key in (page.get("url"), page.get("final_url")):
                if isinstance(key, str):
                    pages[key] = page
        detail = ", ".join(str(e.get("code", "error")) for e in errors)[:180]
        await record("fetch", "ok" if fetched else "error", detail, len(fetched), started)
    except tinyfish.TinyFishError as error:
        await record("fetch", "error", error.code, 0, started)

    retrieved = datetime.now(timezone.utc).isoformat()
    sources: list[dict[str, Any]] = []
    for item in chosen:
        page = pages.get(item["url"])
        body = str(page.get("text") or "") if page else ""
        text = condense(body, patterns) if body.strip() else item["snippet"]
        if not text.strip():
            continue
        sources.append(
            {
                "title": str((page or {}).get("title") or item["title"]),
                "url": item["url"],
                "domain": _domain(item["url"]),
                "text": text,
                "snippet": item["snippet"],
                "retrieved_at": retrieved,
                "origin": "tinyfish_live",
            }
        )
    if not sources:
        raise tinyfish.TinyFishError("empty", "no readable pages")
    return _number(sources)


async def gather_guidance(topic: dict[str, Any], language: str) -> dict[str, Any]:
    """Return {mode, sources, calls}. mode is live, cached or offline."""
    calls: list[dict[str, Any]] = []

    async def record(kind: str, status: str, detail: str, count: int, started: float | None) -> None:
        elapsed = int((time.monotonic() - started) * 1000) if started else 0
        calls.append(
            {"kind": kind, "status": status, "detail": detail, "result_count": count,
             "elapsed_ms": elapsed, "query": topic["query"] if kind != "cache" else topic["id"]}
        )
        await _db(
            store.log_call, kind=kind, topic=topic["id"], query_text=topic["query"],
            status=status, detail=detail, result_count=count, elapsed_ms=elapsed,
        )

    cached = await _db(store.get_cache, topic["id"])
    if cached and store.is_fresh(cached[1], CACHE_HOURS):
        await record("cache", "hit", "fresh guidance reused", len(cached[0]), None)
        return {"mode": "cached", "sources": _number(list(cached[0])), "calls": calls}

    if tinyfish.api_key() is None:
        await record("search", "skipped", "TINYFISH_API_KEY is not set", 0, None)
    else:
        try:
            sources = await _live_sources(topic, record)
            await _db(store.put_cache, topic["id"], sources)
            return {"mode": "live", "sources": sources, "calls": calls}
        except tinyfish.TinyFishError as error:
            await record("search", "error", error.code, 0, None)
        except Exception:  # noqa: BLE001 - never let guidance crash the chat
            logger.exception("Unexpected TinyFish failure")
            await record("search", "error", "unexpected", 0, None)

    if cached:
        await record("cache", "stale", "using older saved guidance", len(cached[0]), None)
        return {"mode": "cached", "sources": _number(list(cached[0])), "calls": calls}
    return {"mode": "offline", "sources": offline_sources(topic, language), "calls": calls}


_STOP = {
    "this", "that", "what", "when", "where", "which", "with", "have", "does", "should", "would", "could",
    "there", "their", "about", "from", "into", "your", "mine", "than", "then", "them", "they", "will",
    "just", "very", "much", "more", "some", "been", "being", "will", "wound", "normal",
}
_JUNK = re.compile(
    r"cookie|©|copyright|subscribe|sign up|skip to|privacy|terms of|follow us|share this|"
    r"\bmenu\b|log ?in|javascript|advert|newsletter|download|donate|nearest A&E",
    re.I,
)
# Sources are often UK pages. Their emergency numbers would mislead users in India,
# so sentences that name them are dropped and urgency lead-ins are relabelled.
_UK_ONLY = re.compile(r"\b(999|111|A&E|NHS)\b")
_LEAD_URGENT = re.compile(r"urgent|appointment|\b111\b", re.I)
_LEAD_EMERGENCY = re.compile(r"immediate action|\b999\b|A&E|emergency", re.I)


def _relabel_lead(lead: str) -> str:
    if _LEAD_EMERGENCY.search(lead):
        return "Get emergency help if:"
    if _LEAD_URGENT.search(lead):
        return "See a doctor soon if:"
    return lead
_ACTION = re.compile(r"\b(should|keep|contact|call|seek|clean|change|avoid|watch|see a|get medical|wash|cover)\b", re.I)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    return re.sub(r"[`*#>|]+", " ", text)


def split_sentences(text: str) -> list[str]:
    """Readable sentences from a page, with menus, links and boilerplate dropped.

    A bullet that follows a lead-in such as "Urgent advice: ask for a GP if:"
    keeps that lead-in, so the advice is never shown without its condition.
    """
    found: list[str] = []
    lead = ""
    for raw in re.split(r"\n+", text):
        line = _strip_markdown(raw).strip()
        if not line:
            continue
        is_heading = raw.lstrip().startswith("#")
        is_bullet = bool(re.match(r"^\s*([*\-\u2022]|\d+[.)])\s", raw))
        line = re.sub(r"^[\s\-\u2022\d.)]+", "", line).strip()
        line = re.sub(r"\s+", " ", line)
        if line.endswith(":"):
            lead = _relabel_lead(line.rstrip(":").strip() + ":")
            continue
        if is_heading:
            lead = ""
            continue
        parts = [line] if is_bullet else re.split(r"(?<=[.!?])\s+(?=[A-Z])", line)
        for part in parts:
            sentence = part.strip()
            if is_bullet and lead:
                sentence = f"{lead} {sentence}"
            if (
                35 <= len(sentence) <= 380
                and len(sentence.split()) >= 6
                and not _JUNK.search(sentence)
                and not _UK_ONLY.search(sentence)
                and sentence not in found
            ):
                found.append(sentence)
        if not is_bullet:
            lead = ""
    return found


def question_terms(message: str) -> set[str]:
    words = re.findall(r"[a-z]{4,}", message.lower())
    return {w for w in words if w not in _STOP}


def pick_sentences(
    text: str,
    topic_patterns: list[re.Pattern[str]],
    terms: set[str],
    count: int,
    taken: set[str],
) -> list[str]:
    """The sentences that best match the topic and the question, in page order.

    A sentence must match the topic or the question to be considered at all;
    generic words like "call" or "doctor" only break ties.
    """
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(split_sentences(text)):
        key = sentence.lower()
        if key in taken:
            continue
        topic_hits = sum(1 for pattern in topic_patterns if pattern.search(sentence))
        term_hits = sum(1 for term in terms if term in key)
        if topic_hits + term_hits == 0:
            continue
        generic_hits = sum(1 for pattern in _compile(GENERIC_PATTERNS) if pattern.search(sentence))
        urgent = 2 if sentence.startswith(("See a doctor soon if:", "Get emergency help if:")) else 0
        score = topic_hits * 3 + term_hits * 3 + generic_hits + urgent + (1 if _ACTION.search(sentence) else 0)
        scored.append((score, index, sentence))
    chosen: list[tuple[int, str]] = []
    total = 0
    for score, index, sentence in sorted(scored, key=lambda item: (-item[0], item[1])):
        if len(chosen) == count or total + len(sentence) > 560:
            continue
        chosen.append((index, sentence))
        total += len(sentence)
    ordered = [sentence for _, sentence in sorted(chosen)]
    taken.update(sentence.lower() for sentence in ordered)
    return ordered


def extractive_answer(
    sources: list[dict[str, Any]], topic: dict[str, Any], language: str, offline: bool, message: str = ""
) -> tuple[str, list[int]]:
    """An answer made only of sentences from the sources. No language model."""
    patterns = _compile(topic["en"] + GENERIC_PATTERNS)
    topic_patterns = _compile(topic["en"])
    terms = question_terms(message)
    lead = (LEAD_OFFLINE if offline else LEAD_LIVE)[language]
    taken: set[str] = set()
    lines: list[str] = []
    used: list[int] = []
    for rank, source in enumerate(sources[:2]):
        body = str(source.get("text") or source.get("snippet") or "")
        picked = pick_sentences(body, topic_patterns, terms, 3 if rank == 0 else 2, taken)
        if picked:
            lines.append("\n".join(f"\u2022 {sentence}" for sentence in picked) + f" [{source['n']}]")
            used.append(source["n"])
        elif (excerpt := best_excerpt(body, patterns)) and not _JUNK.search(excerpt) and any(
            pattern.search(excerpt) for pattern in patterns
        ):
            lines.append(f"{excerpt} [{source['n']}]")
            used.append(source["n"])
    if not lines:
        return NOT_SURE[language], []
    return lead + "\n\n" + "\n\n".join(lines), used


async def answer(
    message: str, language: str, wound_state: dict[str, str] | None
) -> dict[str, Any]:
    lang = "hi" if language == "hi" else "en"
    topic = pick_topic(message)
    flags = detect_red_flags(message)
    escalate = bool(flags) or bool(wound_state and wound_state.get("status") == "see_doctor_today")

    guidance = await gather_guidance(topic, lang)
    sources: list[dict[str, Any]] = guidance["sources"]
    mode: str = guidance["mode"]

    if mode == "offline":
        text, cited = sources[0]["text"], [1]
        text = f"{LEAD_OFFLINE[lang]}\n\n{text} [1]"
    else:
        text, cited = extractive_answer(sources, topic, lang, offline=False, message=message)

    citations = [
        {
            "n": s["n"], "title": s["title"], "url": s["url"], "domain": s["domain"],
            "retrieved_at": s["retrieved_at"], "origin": s["origin"],
        }
        for s in sources
        if s["n"] in cited
    ]
    return {
        "answer": text,
        "citations": citations,
        "needs_doctor": escalate,
        "escalation": ESCALATION[lang] if escalate else None,
        "red_flags": flags,
        "guidance": {
            "mode": mode,
            "topic": topic["id"],
            "query_sent": topic["query"] if any(c["kind"] == "search" and c["status"] == "ok" for c in guidance["calls"]) else None,
            "source_count": len(sources) if mode != "offline" else 0,
            "domain_count": len({s["domain"] for s in sources}) if mode != "offline" else 0,
        },
        "calls": guidance["calls"],
    }
