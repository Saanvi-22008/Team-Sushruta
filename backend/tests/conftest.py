"""Shared fixtures for the API/dose tests (FEAT-004).

Builds a FastAPI app wired to a fresh in-memory SQLite DB per test and provides
helpers to seed a wound + readings. The ``get_session`` dependency is overridden
so every request in a test shares the one in-memory engine (SQLite in-memory DBs
are per-connection, so a StaticPool keeps a single shared connection).
"""

from __future__ import annotations

import os
import sys

# Ensure this tests directory is importable so sibling helper modules
# (e.g. ``_helpers``) resolve regardless of pytest's import mode.
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.db import create_all, make_engine, make_session_factory


@pytest.fixture()
def good_config():
    cfg = load_config()
    assert cfg.loaded
    return cfg


@pytest.fixture()
def engine():
    eng = make_engine("sqlite://")  # shared in-memory (StaticPool)
    create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture()
def db_session(session_factory) -> Session:
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


def _build_client(cfg, session_factory):
    from app.api.deps import get_session
    from app.main import create_app

    app = create_app(config=cfg, init_db=False)

    def _override_session():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override_session
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def client(good_config, session_factory):
    return _build_client(good_config, session_factory)


@pytest.fixture()
def client_factory(session_factory):
    """Return a builder so a test can supply its own (e.g. fail-safe) config."""

    def _factory(cfg):
        return _build_client(cfg, session_factory)

    return _factory
