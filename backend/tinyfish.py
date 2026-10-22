"""Server-side TinyFish client (Search and Fetch).

The API key is read from the TINYFISH_API_KEY environment variable and is only
ever sent from this server. It never reaches the mobile app or git.

Privacy rule: callers pass generic medical topics only. Nothing about a patient
(name, phone, readings, document text) may be put in `query` or `purpose`.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

SEARCH_URL = "https://api.search.tinyfish.ai/"
FETCH_URL = "https://api.fetch.tinyfish.ai/"


class TinyFishError(Exception):
    """A TinyFish request failed. `code` is a short machine-readable reason."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def api_key() -> str | None:
    return os.getenv("TINYFISH_API_KEY") or None


def host_allowed(url: str, domains: list[str]) -> bool:
    """True if the URL's host is one of the domains or a subdomain of one."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


def _headers() -> dict[str, str]:
    key = api_key()
    if not key:
        raise TinyFishError("no_key", "TINYFISH_API_KEY is not set")
    return {"X-API-Key": key, "Accept": "application/json"}


def _check(response: httpx.Response) -> None:
    code = response.status_code
    if code < 400:
        return
    if code in (401, 403):
        raise TinyFishError("auth", f"HTTP {code}")
    if code == 402:
        raise TinyFishError("out_of_credits", "HTTP 402")
    if code == 429:
        raise TinyFishError("rate_limited", "HTTP 429")
    if code >= 500:
        raise TinyFishError("server_error", f"HTTP {code}")
    raise TinyFishError("bad_request", f"HTTP {code}")


async def search(
    query: str,
    *,
    purpose: str,
    include_domains: list[str],
    language: str = "en",
    client: httpx.AsyncClient | None = None,
    timeout: float = 12.0,
) -> list[dict[str, str]]:
    """Search the web, restricted to the given domains."""
    params = {
        "query": query,
        "purpose": purpose,
        "include_domains": ",".join(include_domains),
        "language": language,
    }
    headers = _headers()
    owns = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.get(SEARCH_URL, params=params, headers=headers)
        _check(response)
        data: dict[str, Any] = response.json()
    except httpx.HTTPError as error:
        raise TinyFishError("network", type(error).__name__) from error
    except ValueError as error:
        raise TinyFishError("bad_response", "not JSON") from error
    finally:
        if owns:
            await http.aclose()

    results: list[dict[str, str]] = []
    for item in data.get("results") or []:
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        results.append(
            {
                "title": str(item.get("title") or url),
                "url": url,
                "snippet": str(item.get("snippet") or ""),
                "site_name": str(item.get("site_name") or ""),
            }
        )
    return results


async def fetch(
    urls: list[str],
    *,
    purpose: str,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
    ttl: int = 43_200,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch pages as markdown. One failed URL does not fail the request."""
    body = {"urls": urls[:10], "format": "markdown", "purpose": purpose, "ttl": ttl}
    headers = _headers()
    owns = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.post(FETCH_URL, json=body, headers=headers)
        _check(response)
        data: dict[str, Any] = response.json()
    except httpx.HTTPError as error:
        raise TinyFishError("network", type(error).__name__) from error
    except ValueError as error:
        raise TinyFishError("bad_response", "not JSON") from error
    finally:
        if owns:
            await http.aclose()

    results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
    errors = [e for e in (data.get("errors") or []) if isinstance(e, dict)]
    return results, errors


# ----------------------------------------------------------------- Agent ----
# The TinyFish Agent drives a real browser to reach a goal on a website. Runs are
# started with /run-async and then polled with GET /v1/runs/{id}.
AGENT_RUN_URL = "https://agent.tinyfish.ai/v1/automation/run-async"
AGENT_STATUS_URL = "https://agent.tinyfish.ai/v1/runs/{run_id}"


def _agent_error(error: Any) -> TinyFishError | None:
    """Map a TinyFish run error object to one of our short codes."""
    if not isinstance(error, dict):
        return None
    category = str(error.get("category") or "").upper()
    if category == "BILLING_FAILURE":
        return TinyFishError("out_of_credits", str(error.get("message") or ""))
    if category == "AGENT_FAILURE":
        return TinyFishError("agent_failed", str(error.get("message") or ""))
    return TinyFishError("server_error", str(error.get("message") or "run failed"))


async def agent_start(
    url: str,
    goal: str,
    output_schema: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 20.0,
) -> str:
    """Start a browser-agent run and return its run id."""
    body = {"url": url, "goal": goal, "output_schema": output_schema, "browser_profile": "lite"}
    headers = _headers()
    owns = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.post(AGENT_RUN_URL, json=body, headers=headers)
        _check(response)
        data: dict[str, Any] = response.json()
    except httpx.HTTPError as error:
        raise TinyFishError("network", type(error).__name__) from error
    except ValueError as error:
        raise TinyFishError("bad_response", "not JSON") from error
    finally:
        if owns:
            await http.aclose()
    run_id = data.get("run_id") or data.get("runId") or data.get("id")
    if not isinstance(run_id, str) or not run_id:
        raise TinyFishError("bad_response", "no run id")
    return run_id


async def agent_status(
    run_id: str, *, client: httpx.AsyncClient | None = None, timeout: float = 20.0
) -> dict[str, Any]:
    """Current state of a run: {status, result}. Raises when the run failed."""
    headers = _headers()
    owns = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.get(AGENT_STATUS_URL.format(run_id=run_id), headers=headers)
        _check(response)
        data: dict[str, Any] = response.json()
    except httpx.HTTPError as error:
        raise TinyFishError("network", type(error).__name__) from error
    except ValueError as error:
        raise TinyFishError("bad_response", "not JSON") from error
    finally:
        if owns:
            await http.aclose()
    status = str(data.get("status") or "").upper()
    if status in ("FAILED", "CANCELLED"):
        raise _agent_error(data.get("error")) or TinyFishError("agent_failed", status)
    return {"status": status, "result": data.get("result")}
