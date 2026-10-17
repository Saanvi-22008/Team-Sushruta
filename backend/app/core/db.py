"""Database engine/session wiring for the Sushruta safety core.

Provides an engine factory (SQLite file for dev, in-memory for tests), WAL
pragma for file-backed DBs, a create-all helper and a FastAPI-compatible
session dependency.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models_db import Base

DEFAULT_DB_URL = os.environ.get("SUSHRUTA_DB_URL", "sqlite:///./sushruta.db")


def _is_memory_url(url: str) -> bool:
    return url in ("sqlite://", "sqlite:///:memory:")


def make_engine(db_url: str | None = None) -> Engine:
    """Create an engine.

    - A URL of ``sqlite://`` / ``sqlite:///:memory:`` yields a shared in-memory
      DB (StaticPool) suitable for tests.
    - A file-backed SQLite URL enables WAL for better concurrency.
    """
    url = db_url or DEFAULT_DB_URL

    if _is_memory_url(url):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    else:
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            future=True,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def create_all(engine: Engine) -> None:
    """Create all tables (migrations-lite for this proof of concept)."""
    Base.metadata.create_all(engine)


# Module-level default wiring used by the FastAPI app.
_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def init_engine(db_url: str | None = None) -> Engine:
    """Initialise (idempotently) the module-level engine + session factory."""
    global _engine, _SessionFactory
    if _engine is None:
        _engine = make_engine(db_url)
        _SessionFactory = make_session_factory(_engine)
        create_all(_engine)
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    if _SessionFactory is None:
        init_engine()
    assert _SessionFactory is not None
    session = _SessionFactory()
    try:
        yield session
    finally:
        session.close()
