"""The direct-POST HTTP device path.

A networked device (or any edge source) delivers a reading by POSTing it to the
ingestion API's ``POST /readings`` endpoint, going through exactly the same
server-side validation + deterministic evaluation as every other source. This
module is a thin, documented client for that flow — it adds no logic that could
diverge from the server contract.

``HttpDevice`` validates each reading against :class:`ReadingIn` client-side
(fail fast, and strip any server-added marker like ``simulated`` that the strict
contract forbids) and POSTs the clean body. The underlying ``httpx`` client is
injectable so the same code is exercised by an in-process ``TestClient`` in
tests and a real network client in production.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from app.core.schemas import ReadingIn


class _HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class _HttpClient(Protocol):
    """Minimal client surface used here (``httpx.Client`` satisfies it)."""

    def post(self, url: str, *, json: Any) -> _HttpResponse: ...


class HttpDeviceError(RuntimeError):
    """Raised when the ingestion API rejects a reading (non-2xx)."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"ingestion API returned {status_code}: {detail}")


class HttpDevice:
    """POST readings to the ingestion API over HTTP (the networked-device path).

    Parameters
    ----------
    client:
        An ``httpx.Client``-like object (anything with ``post(url, json=...)``).
        Tests pass a FastAPI ``TestClient`` to exercise the real server in-proc.
    base_url:
        Base URL of the API (e.g. ``http://127.0.0.1:8000``). May be empty when
        ``client`` already carries a base URL (as a ``TestClient`` does).
    """

    source = "http"

    def __init__(self, client: _HttpClient, base_url: str = "") -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}" if self._base_url else path

    @staticmethod
    def _clean(reading: dict[str, Any]) -> dict[str, Any]:
        """Validate + normalise one reading to the strict wire contract.

        Drops any server-side marker the contract forbids (e.g. ``simulated``),
        then re-serialises through :class:`ReadingIn` so the POSTed body always
        matches ``additionalProperties: false``.
        """
        wire = {k: v for k, v in reading.items() if k != "simulated"}
        return ReadingIn.model_validate(wire).model_dump(mode="json")

    def post_reading(self, reading: dict[str, Any]) -> dict[str, Any]:
        """POST one reading; return the parsed ``ReadingAccepted`` JSON body.

        Raises :class:`HttpDeviceError` on any non-2xx response (so a caller can
        decide whether to retry or skip). A 409 duplicate is treated as an error
        here because the device asserted it was sending a new reading.
        """
        body = self._clean(reading)
        resp = self._client.post(self._url("/readings"), json=body)
        if resp.status_code // 100 != 2:
            detail: Any
            try:
                detail = resp.json()
            except Exception:  # response was not JSON
                detail = getattr(resp, "text", "<no body>")
            raise HttpDeviceError(resp.status_code, detail)
        return resp.json()
