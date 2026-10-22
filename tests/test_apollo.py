import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import apollo, store, tinyfish


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


# ------------------------------------------------ answer built from pages ---
PAGE = """
# Wound care
Skip to main content. Sign up to our newsletter for updates.
Keep the wound clean and covered, and change the dressing when it becomes wet or dirty.
Signs of infection include spreading redness, swelling, pus, a bad smell, and a fever.
Contact a doctor if the redness spreads or you develop a fever.
[Read more about scars](https://example.org/scars)
Scars fade slowly over many months and may look pink at first.
"""


def test_sentences_drop_menus_and_links():
    sentences = apollo.split_sentences(PAGE)
    joined = " ".join(sentences)
    assert "Skip to main" not in joined and "newsletter" not in joined and "http" not in joined
    assert any("pus" in s for s in sentences)


def test_answer_picks_sentences_that_match_the_question():
    topic = apollo.pick_topic("is it infected?")
    source = {"n": 1, "title": "T", "domain": "nhs.uk", "text": PAGE, "snippet": ""}
    text, used = apollo.extractive_answer([source], topic, "en", offline=False, message="is it infected, I see pus")
    assert used == [1]
    assert "pus" in text and "[1]" in text
    assert "Scars fade" not in text


def test_answer_never_contains_text_outside_the_sources():
    topic = apollo.pick_topic("is it infected?")
    source = {"n": 1, "title": "T", "domain": "nhs.uk", "text": PAGE, "snippet": ""}
    text, _ = apollo.extractive_answer([source], topic, "en", offline=False, message="pus?")
    body = text.split("\n\n", 1)[1].replace(" [1]", "")
    for line in body.splitlines():
        assert line.removeprefix("\u2022 ").strip(" .") in PAGE


def test_page_with_nothing_relevant_says_not_sure():
    topic = apollo.pick_topic("can I swim?")
    source = {"n": 1, "title": "T", "domain": "nhs.uk", "text": "Cookie settings. Menu. Log in.", "snippet": ""}
    text, used = apollo.extractive_answer([source], topic, "en", offline=False, message="can I swim")
    assert text == apollo.NOT_SURE["en"] and used == []


def test_chat_response_has_no_llm_field(live):
    reply = asyncio.run(apollo.answer("is it infected?", "en", None))
    assert "llm_used" not in reply["guidance"]


UK_PAGE = """
## Urgent advice: Ask for an urgent GP appointment or get help from NHS 111 if:

* a cut is swollen, red and getting more painful or pus is coming out of it

You can call 111 or get help from 111 online.

## Immediate action required: Call 999 or go to A&E if:

* you have a cut and cannot stop the bleeding
"""


def test_uk_phone_numbers_never_reach_the_user():
    sentences = apollo.split_sentences(UK_PAGE)
    joined = " ".join(sentences)
    for banned in ("111", "999", "A&E", "NHS"):
        assert banned not in joined
    assert any(s.startswith("See a doctor soon if: a cut is swollen") for s in sentences)
    assert any(s.startswith("Get emergency help if: you have a cut and cannot stop the bleeding") for s in sentences)


def test_bullets_keep_their_condition():
    topic = apollo.pick_topic("pus and swelling")
    source = {"n": 1, "title": "T", "domain": "nhs.uk", "text": UK_PAGE, "snippet": ""}
    text, _ = apollo.extractive_answer([source], topic, "en", offline=False, message="pus and swelling")
    assert "See a doctor soon if:" in text
