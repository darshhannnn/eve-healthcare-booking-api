"""Authentication: signup, login (both formats), JWT, validation edge cases."""


def test_health_and_docs(client):
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_signup_success(client):
    resp = client.post(
        "/auth/signup",
        json={"email": "riya@example.com", "password": "Str0ngPass!23", "full_name": "Riya Sharma"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "riya@example.com"
    assert body["role"] == "USER"
    assert "hashed_password" not in body and "password" not in body


def test_signup_normalises_email_case(client):
    client.post(
        "/auth/signup",
        json={"email": "Case@Example.COM", "password": "Str0ngPass!23", "full_name": "A"},
    )
    resp = client.post(
        "/auth/signup",
        json={"email": "case@example.com", "password": "Str0ngPass!23", "full_name": "B"},
    )
    assert resp.status_code == 409


def test_signup_duplicate_email_conflict(client):
    payload = {"email": "dup@example.com", "password": "Str0ngPass!23", "full_name": "A"}
    assert client.post("/auth/signup", json=payload).status_code == 201
    resp = client.post("/auth/signup", json={**payload, "full_name": "B"})
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"].lower()


def test_signup_invalid_email_422(client):
    resp = client.post(
        "/auth/signup",
        json={"email": "not-an-email", "password": "Str0ngPass!23", "full_name": "A"},
    )
    assert resp.status_code == 422


def test_signup_short_password_422(client):
    resp = client.post(
        "/auth/signup",
        json={"email": "shortpw@example.com", "password": "short", "full_name": "A"},
    )
    assert resp.status_code == 422


def test_signup_blank_name_422(client):
    resp = client.post(
        "/auth/signup",
        json={"email": "blank@example.com", "password": "Str0ngPass!23", "full_name": "  "},
    )
    assert resp.status_code == 422


def test_login_json_ok(client):
    from tests.helpers import signup

    user = signup(client)
    resp = client.post("/auth/login", json={"email": user.email, "password": user.password})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    assert body["expires_in"] > 0


def test_login_oauth2_form_ok(client):
    from tests.helpers import signup

    user = signup(client)
    resp = client.post(
        "/auth/login",
        data={"username": user.email, "password": user.password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_login_wrong_password_401(client):
    from tests.helpers import signup

    user = signup(client)
    resp = client.post("/auth/login", json={"email": user.email, "password": "WrongPass!99"})
    assert resp.status_code == 401


def test_login_unknown_user_401(client):
    resp = client.post("/auth/login", json={"email": "ghost@example.com", "password": "Whatever!1"})
    assert resp.status_code == 401


def test_login_invalid_json_422(client):
    resp = client.post("/auth/login", content=b"{not json",
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 422


def test_me_requires_token_401(client):
    assert client.get("/auth/me").status_code == 401


def test_me_with_bad_token_401(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_me_returns_profile(client):
    from tests.helpers import make_user

    user = make_user(client)
    resp = client.get("/auth/me", headers=user.headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == user.email
