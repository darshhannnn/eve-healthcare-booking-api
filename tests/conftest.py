"""Pytest fixtures: a fresh in-memory SQLite database per test, with the app's
lifespan (admin seeding) running against it."""

import os

# Test configuration must be set before the app (and its cached Settings) load.
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("SEED_DEMO_DATA", "false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db, set_engine
from app.main import app


@pytest.fixture()
def db_engine():
    """Point the app at an isolated database.

    Default: a fresh in-memory SQLite database (shared connection pool so
    the app and test assertions see the same data). When DATABASE_URL points
    at PostgreSQL (CI's postgres job), use it instead — the schema is
    recreated per test, which is what lets the row-locking concurrency test
    run for real.
    """
    url = get_settings().DATABASE_URL
    if url.startswith(("postgres", "postgresql")):
        engine = create_engine(url)
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        set_engine(engine)
        yield engine
        set_engine(None)
        engine.dispose()
        return

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    set_engine(engine)
    yield engine
    set_engine(None)
    engine.dispose()


@pytest.fixture()
def client(db_engine):
    from app.utils.cache import cache_clear

    cache_clear()  # never leak cached listings across tests

    TestingSessionLocal = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:  # context manager triggers lifespan (seeds admin)
        yield test_client
    app.dependency_overrides.pop(get_db, None)
