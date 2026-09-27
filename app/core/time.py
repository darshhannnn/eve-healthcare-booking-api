"""Datetime helpers.

The API normalises every timestamp to timezone-aware UTC. SQLite (used for
local dev and tests) stores naive values, while PostgreSQL ``timestamptz``
returns aware ones — ``ensure_utc`` makes comparisons safe on both dialects.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as a timezone-aware datetime in UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
