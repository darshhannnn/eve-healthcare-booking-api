"""Rate limiting on auth endpoints."""


def test_login_rate_limited_after_limit(client, monkeypatch):
    from app.core.config import get_settings
    from app.utils.rate_limit import reset_rate_limiter
    from tests.helpers import signup, unique_email

    # Sign up while the limiter is off, so the signup doesn't consume budget.
    user = signup(client)

    settings = get_settings()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 3)
    reset_rate_limiter()

    try:
        # 3 attempts within the window pass...
        for _ in range(3):
            resp = client.post(
                "/auth/login", json={"email": user.email, "password": user.password}
            )
            assert resp.status_code == 200

        # ...the 4th is throttled even with correct credentials.
        resp = client.post("/auth/login", json={"email": user.email, "password": user.password})
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

        # Signup shares the same scope/budget.
        resp = client.post(
            "/auth/signup",
            json={"email": unique_email(), "password": "Str0ngPass!23", "full_name": "R"},
        )
        assert resp.status_code == 429
    finally:
        reset_rate_limiter()


def test_rate_limit_disabled_by_test_env(client):
    """RATE_LIMIT_ENABLED=false (set in conftest) lets many logins through."""
    from tests.helpers import make_user

    user = make_user(client)
    for _ in range(5):
        resp = client.post("/auth/login", json={"email": user.email, "password": user.password})
        assert resp.status_code == 200


def test_mutating_endpoints_rate_limited(client, monkeypatch):
    """POST /bookings, /payments and cancel share a fixed window per IP."""
    from app.core.config import get_settings
    from app.utils.rate_limit import reset_rate_limiter
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, future_iso,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)

    settings = get_settings()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_MUTATIONS_PER_MINUTE", 2)
    reset_rate_limiter()
    try:
        bodies = [
            {"centre_id": data["centre"]["id"], "test_id": data["test"]["id"],
             "appointment_at": future_iso(days=days)}
            for days in (2, 3, 4)
        ]
        assert client.post("/bookings", headers=user.headers, json=bodies[0]).status_code == 201
        assert client.post("/bookings", headers=user.headers, json=bodies[1]).status_code == 201
        resp = client.post("/bookings", headers=user.headers, json=bodies[2])
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
    finally:
        reset_rate_limiter()


def test_rate_limiter_ignores_forwarded_for_by_default(client, monkeypatch):
    """Secure default: a spoofed X-Forwarded-For must not buy a fresh budget."""
    from app.core.config import get_settings
    from app.utils.rate_limit import reset_rate_limiter
    from tests.helpers import signup

    user = signup(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 1)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    reset_rate_limiter()
    try:
        first = client.post(
            "/auth/login", json={"email": user.email, "password": user.password},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        second = client.post(
            "/auth/login", json={"email": user.email, "password": user.password},
            headers={"X-Forwarded-For": "203.0.113.11"},
        )
        assert first.status_code == 200
        assert second.status_code == 429  # same real client -> shared window
    finally:
        reset_rate_limiter()


def test_rate_limiter_honours_forwarded_for_when_trusted(client, monkeypatch):
    """Behind a trusted proxy, distinct X-Forwarded-For clients get their own
    windows instead of sharing the proxy IP's budget."""
    from app.core.config import get_settings
    from app.utils.rate_limit import reset_rate_limiter
    from tests.helpers import signup

    user = signup(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 1)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    reset_rate_limiter()
    try:
        first = client.post(
            "/auth/login", json={"email": user.email, "password": user.password},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        assert first.status_code == 200
        second = client.post(
            "/auth/login", json={"email": user.email, "password": user.password},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        assert second.status_code == 429  # same forwarded IP -> throttled

        other = client.post(
            "/auth/login", json={"email": user.email, "password": user.password},
            headers={"X-Forwarded-For": "203.0.113.11"},
        )
        assert other.status_code == 200  # different forwarded IP -> own window
    finally:
        reset_rate_limiter()
