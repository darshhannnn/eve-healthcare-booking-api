"""Fixed-window, in-memory rate limiter (per client IP + scope).

Intentionally dependency-free: counters live in a dict guarded by a lock,
which is correct for a single-process deployment. In production the counters
would move to Redis (or the edge/ingress) so limits are shared across
workers — the ``dependency`` shape would not change.
"""

import threading
import time

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

_WINDOW_SECONDS = 60.0

_counters: dict[str, tuple[float, int]] = {}
_lock = threading.Lock()


def rate_limit(scope: str, settings_attr: str = "RATE_LIMIT_AUTH_PER_MINUTE"):
    """Dependency factory enforcing a fixed-window limit per IP.

    The limit value is read from ``settings.<settings_attr>`` on every call
    so it can be tuned at runtime (and monkeypatched in tests).
    """

    def dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.RATE_LIMIT_ENABLED:
            return
        limit = getattr(settings, settings_attr)
        if limit <= 0:
            return
        client_ip = request.client.host if request.client else "unknown"
        key = f"{scope}:{client_ip}"
        now = time.monotonic()

        with _lock:
            window_start, count = _counters.get(key, (now, 0))
            if now - window_start >= _WINDOW_SECONDS:
                window_start, count = now, 0
            if count + 1 > limit:
                retry_after = max(1, int(_WINDOW_SECONDS - (now - window_start)) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please slow down and try again shortly.",
                    headers={"Retry-After": str(retry_after)},
                )
            _counters[key] = (window_start, count + 1)

    return dependency


def reset_rate_limiter() -> None:
    """Clear all counters (used by the test suite)."""
    with _lock:
        _counters.clear()
