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
