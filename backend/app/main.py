"""FastAPI application for the Sushruta safety core.

Wires dependency injection (safety config + DB session), registers the routers,
and exposes ``GET /health`` with the config fail-safe:

- 200 when the safety config loaded cleanly.
- 503 when the config load-error flag is set — and, because the decision
  endpoints depend on :func:`app.api.deps.require_config`, they also return 503
  in that state (fail-safe, no unsafe default).

Run (dev):  ``uvicorn app.main:app --reload`` from the ``backend`` directory,
or ``python -m app.main``.
"""

from __future__ import annotations

import threading
from collections import defaultdict

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api import dose, readings, status
from app.core.config import SafetyConfig, load_config
from app.core.db import init_engine

APP_NAME = "Sushruta Safety Core"


def create_app(
    config: SafetyConfig | None = None,
    *,
    db_url: str | None = None,
    init_db: bool = True,
) -> FastAPI:
    """Build and configure the FastAPI app.

    Parameters
    ----------
    config:
        An explicit :class:`SafetyConfig` (tests inject a fail-safe one to prove
        the 503 behaviour). Defaults to :func:`load_config`.
    db_url:
        Optional DB URL override (tests pass an in-memory URL).
    init_db:
        When False, skip initialising the module-level engine (tests override
        the ``get_session`` dependency and do not want a stray dev DB file).
    """
    app = FastAPI(title=APP_NAME)

    # Config loaded once at startup and held on app.state.
    app.state.safety_config = config if config is not None else load_config()

    # Per-wound lock registry (serialises dose requests per wound).
    app.state.wound_locks = defaultdict(threading.Lock)
    app.state.wound_locks_guard = threading.Lock()

    # Initialise the DB engine/tables (idempotent).
    if init_db:
        init_engine(db_url)

    @app.get("/health", tags=["health"])
    def health() -> JSONResponse:
        cfg: SafetyConfig = app.state.safety_config
        if not cfg.loaded:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unavailable",
                    "detail": "Safety configuration missing or unparseable.",
                    "load_error": cfg.load_error,
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "config_snapshot": cfg.config_snapshot,
            },
        )

    app.include_router(readings.router)
    app.include_router(status.router)
    app.include_router(dose.router)
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover - manual dev entry point
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
