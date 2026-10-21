"""Tests always run against a throwaway SQLite file, never the real database."""

import os
import tempfile

_DB_FILE = os.path.join(tempfile.mkdtemp(prefix="sushruta-tests-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE}"
for key in ("TINYFISH_API_KEY", "GEMINI_API_KEY", "SARVAM_API_KEY"):
    os.environ.pop(key, None)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_tables():
    from backend.database import Base, engine
    import backend.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
