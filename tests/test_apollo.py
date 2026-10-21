import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import apollo, llm, store, tinyfish


# ---------------------------------------------------------------- privacy ---
def test_every_topic_query_is_generic_and_fixed():
    """TinyFish only ever receives these fixed topic queries, never user text."""
    queries = [t["query"] for t in apollo.TOPICS] + [apollo.GENERAL_TOPIC["query"]]
    assert len(queries) == len(set(queries))
    for query in queries:
        assert len(query) < 100
        assert not any(ch.isdigit() for ch in query)


def test_user_text_never_reaches_tinyfish(monkeypatch):
    sent: list[str] = []

    async def fake_search(query, **kwargs):
        sent.append(query + " " + kwargs.get("purpose", ""))
        return []

    monkeypatch.setenv("TINYFISH_API_KEY", "test-key")
    monkeypatch.setattr(tinyfish, "search", fake_search)
    message = "I am Meera Sharma, phone 9811163946, my wound has pus"
    asyncio.run(apollo.answer(message, "en", None))
    assert sent, "search should have been attempted"
    joined = " ".join(sent).lower()
    for secret in ("meera", "sharma", "9811163946"):
        assert secret not in joined


# ----------------------------------------------------------- topic + flags --
@pytest.mark.parametrize(
    "message,topic",
    [
        ("There is pus and swelling", "infection_signs"),
        ("what does wound pH mean", "ph"),
        ("my bandage is wet, how often change", "moisture_dressing"),
        ("मवाद है", "infection_signs"),
        ("hello", "general"),
    ],
)
def test_topic_selection(message, topic):
    assert apollo.pick_topic(message)["id"] == topic


@pytest.mark.parametrize(
    "message,flag",
    [
        ("I see pus", "pus"),
        ("the redness is spreading", "spreading_redness"),
        ("I have a fever", "fever"),
        ("it is a dog bite", "bite_or_puncture"),
        ("bad smell from the wound", "bad_smell"),
        ("बुखार है", "fever"),
        ("मवाद आ रहा है", "pus"),
    ],
)
def test_red_flags_detected(message, flag):
    assert flag in apollo.detect_red_flags(message)


@pytest.mark.parametrize("message", ["there is no pus", "no fever today", "मवाद नहीं है", "hello"])
def test_negated_or_absent_flags_are_ignored(message):
    assert apollo.detect_red_flags(message) == []


# ------------------------------------------------------- citation validation -
def test_llm_answer_with_unknown_source_is_rejected():
    assert apollo.validate_llm_answer({"answer": "Do X [3]", "citations": [3], "covered": True}, 2) is None
    assert apollo.validate_llm_answer({"answer": "Do X [1]", "citations": [1, 4], "covered": True}, 2) is None
    assert apollo.validate_llm_answer({"answer": "Do X [9]", "citations": [1], "covered": True}, 2) is None


def test_llm_answer_without_citations_is_rejected():
    assert apollo.validate_llm_answer({"answer": "Trust me.", "citations": [], "covered": True}, 2) is None
    assert apollo.validate_llm_answer("not a dict", 2) is None
    assert apollo.validate_llm_answer({"answer": "", "citations": [1], "covered": True}, 2) is None


def test_valid_llm_answer_is_accepted_and_uncovered_is_honoured():
    ok = apollo.validate_llm_answer({"answer": "Keep it clean [1][2].", "citations": [1], "covered": True}, 2)
    assert ok and ok["citations"] == [1, 2]
    unsure = apollo.validate_llm_answer({"answer": "", "citations": [], "covered": False}, 2)
    assert unsure == {"covered": False, "answer": "", "citations": []}


# ------------------------------------------------------------ allow-list ----
def test_allow_list_accepts_subdomains_and_rejects_lookalikes():
    domains = apollo.TRUSTED_DOMAINS
    assert tinyfish.host_allowed("https://www.nhs.uk/conditions/cuts-and-grazes/", domains)
    assert tinyfish.host_allowed("https://www.uhsussex.nhs.uk/x", domains)
    assert tinyfish.host_allowed("https://medlineplus.gov/ency/article/007645.htm", domains)
    assert not tinyfish.host_allowed("https://nhs.uk.evil.example/x", domains)
    assert not tinyfish.host_allowed("https://notnhs.uk/x", domains)
    assert not tinyfish.host_allowed("https://randomblog.com/x", domains)


# --------------------------------------------------------- TinyFish client --
def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_search_and_fetch_parse_responses(monkeypatch):
    monkeypatch.setenv("TINYFISH_API_KEY", "test-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("X-API-Key")
        if request.url.host == "api.search.tinyfish.ai":
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"results": [
                {"title": "Cuts", "url": "https://www.nhs.uk/c", "snippet": "s", "site_name": "nhs"},
                {"title": "bad", "snippet": "no url"},
            ]})
        body = json.loads(request.content)
        seen["body"] = body
        return httpx.Response(200, json={
            "results": [{"url": body["urls"][0], "title": "T", "text": "page text"}],
            "errors": [{"url": body["urls"][1], "code": "bot_blocked"}],
        })

    async def run():
        async with _client(handler) as client:
            results = await tinyfish.search("q", purpose="p", include_domains=["nhs.uk", "cdc.gov"], client=client)
            fetched, errors = await tinyfish.fetch(["https://a", "https://b"], purpose="p", client=client)
            return results, fetched, errors

    results, fetched, errors = asyncio.run(run())
    assert seen["key"] == "test-key"
    assert seen["params"]["include_domains"] == "nhs.uk,cdc.gov"
    assert seen["body"]["format"] == "markdown"
    assert [r["url"] for r in results] == ["https://www.nhs.uk/c"]
    assert fetched[0]["text"] == "page text" and errors[0]["code"] == "bot_blocked"


@pytest.mark.parametrize("status,code", [(401, "auth"), (402, "out_of_credits"), (429, "rate_limited"), (503, "server_error")])
def test_tinyfish_http_errors_become_codes(monkeypatch, status, code):
    monkeypatch.setenv("TINYFISH_API_KEY", "test-key")

    async def run():
        async with _client(lambda r: httpx.Response(status, json={})) as client:
            await tinyfish.search("q", purpose="p", include_domains=["nhs.uk"], client=client)

    with pytest.raises(tinyfish.TinyFishError) as info:
        asyncio.run(run())
    assert info.value.code == code


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    with pytest.raises(tinyfish.TinyFishError) as info:
        asyncio.run(tinyfish.search("q", purpose="p", include_domains=["nhs.uk"]))
    assert info.value.code == "no_key"


# ------------------------------------------------------- full Apollo flow ---
SEARCH = [
    {"title": "Cuts and grazes", "url": "https://www.nhs.uk/conditions/cuts-and-grazes/", "snippet": "See a doctor if the cut is red and painful or has pus.", "site_name": "nhs.uk"},
    {"title": "Random blog", "url": "https://randomblog.com/wounds", "snippet": "ignore", "site_name": "blog"},
    {"title": "Wounds", "url": "https://medlineplus.gov/ency/patientinstructions/000741.htm", "snippet": "Call the doctor for redness.", "site_name": "medlineplus.gov"},
]
PAGE = "Intro paragraph.\n\nContact your provider right away if you have:\n\n* Redness, increased pain, or yellow or green pus. These are signs of infection.\n\nUnrelated gardening paragraph."


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("TINYFISH_API_KEY", "test-key")

    async def fake_search(query, **kwargs):
        return list(SEARCH)

    async def fake_fetch(urls, **kwargs):
        return [{"url": u, "title": "Page " + u[-6:], "text": PAGE} for u in urls], []

    monkeypatch.setattr(tinyfish, "search", fake_search)
    monkeypatch.setattr(tinyfish, "fetch", fake_fetch)


def test_live_answer_uses_allow_listed_sources_only(live):
    reply = asyncio.run(apollo.answer("my wound has pus", "en", None))
    assert reply["guidance"]["mode"] == "live"
    urls = [c["url"] for c in reply["citations"]]
    assert urls and all(tinyfish.host_allowed(u, apollo.TRUSTED_DOMAINS) for u in urls)
    assert "randomblog.com" not in " ".join(urls)
    assert reply["guidance"]["query_sent"] == "signs of wound infection when to see a doctor"
    assert "[1]" in reply["answer"]
    assert reply["needs_doctor"] is True  # "pus" is a red flag


def test_second_question_on_same_topic_uses_cache(live, monkeypatch):
    asyncio.run(apollo.answer("signs of infection?", "en", None))

    async def boom(*a, **k):
        raise AssertionError("TinyFish should not be called again")

    monkeypatch.setattr(tinyfish, "search", boom)
    reply = asyncio.run(apollo.answer("any sign of infection?", "en", None))
    assert reply["guidance"]["mode"] == "cached"


@pytest.mark.parametrize("code_status", [429, 402, 503])
def test_tinyfish_outage_falls_back_to_saved_notes(monkeypatch, code_status):
    monkeypatch.setenv("TINYFISH_API_KEY", "test-key")
    code = {429: "rate_limited", 402: "out_of_credits", 503: "server_error"}[code_status]

    async def failing(*a, **k):
        raise tinyfish.TinyFishError(code)

    monkeypatch.setattr(tinyfish, "search", failing)
    reply = asyncio.run(apollo.answer("how do I change my dressing", "en", None))
    assert reply["guidance"]["mode"] == "offline"
    assert reply["citations"][0]["origin"] == "offline"
    assert reply["citations"][0]["url"] is None
    assert reply["guidance"]["query_sent"] is None


def test_no_key_still_answers_in_hindi_offline(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    reply = asyncio.run(apollo.answer("पट्टी कब बदलें", "hi", None))
    assert reply["guidance"]["mode"] == "offline"
    assert "पट्टी" in reply["answer"]


def test_status_escalation_cannot_be_switched_off(live):
    state = {"status": "see_doctor_today", "ph": "high", "temperature": "normal", "moisture": "normal"}
    reply = asyncio.run(apollo.answer("is it fine to just wait?", "en", state))
    assert reply["needs_doctor"] is True
    assert reply["escalation"] == apollo.ESCALATION["en"]


def test_llm_with_bad_citation_is_replaced_by_extract(live, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")

    async def bad_llm(*a, **k):
        return {"answer": "Definitely fine [7].", "citations": [7], "covered": True}

    monkeypatch.setattr(llm, "generate", bad_llm)
    reply = asyncio.run(apollo.answer("is it infected?", "en", None))
    assert reply["guidance"]["llm_used"] is False
    assert "[7]" not in reply["answer"]


def test_llm_good_answer_is_used(live, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")

    async def good_llm(*a, **k):
        return {"answer": "Pus and spreading redness can mean infection [1].", "citations": [1], "covered": True}

    monkeypatch.setattr(llm, "generate", good_llm)
    reply = asyncio.run(apollo.answer("what are infection signs?", "en", None))
    assert reply["guidance"]["llm_used"] is True
    assert [c["n"] for c in reply["citations"]] == [1]


def test_llm_not_covered_says_not_sure(live, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")

    async def unsure(*a, **k):
        return {"answer": "", "citations": [], "covered": False}

    monkeypatch.setattr(llm, "generate", unsure)
    reply = asyncio.run(apollo.answer("can I swim?", "en", None))
    assert reply["answer"] == apollo.NOT_SURE["en"]
    assert reply["citations"] == []


# ------------------------------------------------------------- HTTP layer ---
def test_chat_endpoint_logs_every_tinyfish_call(live):
    from backend.main import app

    client = TestClient(app)
    response = client.post("/api/apollo/chat", json={"message": "signs of infection", "language": "en"})
    assert response.status_code == 200
    body = response.json()
    assert body["guidance"]["mode"] == "live"
    activity = client.get("/api/tinyfish/activity").json()
    assert {item["kind"] for item in activity} >= {"search", "fetch"}
    assert all(item["query"] == "signs of wound infection when to see a doctor" for item in activity if item["kind"] in ("search", "fetch"))


def test_chat_endpoint_rejects_bad_input():
    from backend.main import app

    client = TestClient(app)
    assert client.post("/api/apollo/chat", json={"message": "", "language": "en"}).status_code == 422
    assert client.post("/api/apollo/chat", json={"message": "x" * 501, "language": "en"}).status_code == 422
    assert client.post("/api/apollo/chat", json={"message": "hi", "language": "fr"}).status_code == 422


def test_health_endpoint_never_returns_secrets(monkeypatch):
    from backend.main import app

    monkeypatch.setenv("TINYFISH_API_KEY", "super-secret-value")
    body = TestClient(app).get("/api/apollo/health").json()
    assert body["tinyfish_key"] is True
    assert "super-secret-value" not in json.dumps(body)


# ---------------------------------------------------------------- Gemini ----
def test_gemini_request_shape_and_parsing(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["key"] = request.headers.get("x-goog-api-key")
        captured["body"] = json.loads(request.content)
        payload = {"answer": "ok [1]", "citations": [1], "covered": True}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})

    sources = [{"n": 1, "title": "T", "domain": "nhs.uk", "text": "body", "snippet": "s"}]

    async def run():
        async with _client(handler) as client:
            return await llm.generate("question", "en", sources, {"status": "all_good"}, client=client)

    result = asyncio.run(run())
    assert result["citations"] == [1]
    assert captured["key"] == "g-key"
    prompt = captured["body"]["contents"][0]["parts"][0]["text"]
    assert "[1] T (nhs.uk)" in prompt and "question" in prompt


def test_gemini_failure_returns_none(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")

    async def run():
        async with _client(lambda r: httpx.Response(500, json={})) as client:
            return await llm.generate("q", "en", [], None, client=client)

    assert asyncio.run(run()) is None
