"""Read-through TTL cache for hot listing/detail endpoints.

Backed by an in-process dict by default; switches to Redis when
``CACHE_BACKEND=redis`` and ``REDIS_URL`` are configured. If Redis is
unreachable the service degrades gracefully to the in-memory backend.
The interface is deliberately tiny (get / set / clear) so the backend can
be swapped without touching call sites.
"""

import json
import logging
import threading
import time
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("eve.cache")

_KEY_PREFIX = "eve:cache:"


class _MemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            with self._lock:
                self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + ttl_seconds, value)

    def clear(self) -> None:
        with self._lock:
            for key in [k for k in self._data if k.startswith(_KEY_PREFIX)]:
                self._data.pop(key, None)


_memory = _MemoryBackend()
_redis_client: Any = None
_redis_checked = False


def _get_redis() -> Any:
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    settings = get_settings()
    if settings.CACHE_BACKEND == "redis" and settings.REDIS_URL:
        try:
            import redis  # type: ignore[import-untyped]

            client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
            client.ping()
            _redis_client = client
            logger.info("cache backend: redis")
        except Exception as exc:  # pragma: no cover — environment dependent
            logger.warning("Redis unavailable (%s); falling back to in-memory cache", exc)
    return _redis_client


def cache_get(key: str) -> Any | None:
    full_key = _KEY_PREFIX + key
    redis = _get_redis()
    if redis is not None:
        raw = redis.get(full_key)
    else:
        raw = _memory.get(full_key)
    return json.loads(raw) if raw is not None else None


def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    full_key = _KEY_PREFIX + key
    raw = json.dumps(value, default=str)
    redis = _get_redis()
    if redis is not None:
        redis.setex(full_key, ttl_seconds, raw)
    else:
        _memory.set(full_key, raw, ttl_seconds)


def cache_clear() -> None:
    """Invalidate all cached entries (called after any admin mutation)."""
    redis = _get_redis()
    if redis is not None:
        keys = list(redis.scan_iter(match=_KEY_PREFIX + "*"))
        if keys:
            redis.delete(*keys)
    else:
        _memory.clear()
