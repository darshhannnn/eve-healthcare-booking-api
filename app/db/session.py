"""Engine and session management.

The engine is created lazily from settings so tests can swap in an
in-memory SQLite engine via :func:`set_engine` before the app starts.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().DATABASE_URL
        kwargs: dict = {}
        if url.startswith("sqlite"):
            # FastAPI runs sync endpoints in a worker threadpool.
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
    return _engine


def set_engine(engine: Engine | None) -> None:
    """Point the app at a specific engine (used by the test suite)."""
    global _engine
    _engine = engine


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = Session(bind=get_engine(), autoflush=False, expire_on_commit=False)
    try:
        yield db
    finally:
        db.close()
