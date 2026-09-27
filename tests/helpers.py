"""Shared builders for users, centres, tests, bookings and webhook signatures."""

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin@12345"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@example.com"


def signup(client, email: str | None = None, password: str = "Str0ngPass!23",
           full_name: str = "Test User"):
    email = email or unique_email()
    resp = client.post(
        "/auth/signup", json={"email": email, "password": password, "full_name": full_name}
    )
    assert resp.status_code == 201, resp.text
    return SimpleNamespace(id=resp.json()["id"], email=email, password=password,
                           full_name=full_name)


def login_token(client, email: str, password: str) -> str:
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def make_user(client, **kwargs):
    user = signup(client, **kwargs)
    user.headers = {"Authorization": f"Bearer {login_token(client, user.email, user.password)}"}
    return user


def admin_user(client):
    token = login_token(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    return SimpleNamespace(email=ADMIN_EMAIL, headers={"Authorization": f"Bearer {token}"})


def create_test(client, admin_headers, code: str | None = None,
                name: str = "Complete Blood Count") -> dict:
    resp = client.post(
        "/tests", headers=admin_headers,
        json={"code": code or f"T{uuid.uuid4().hex[:8].upper()}", "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_centre(client, admin_headers, name: str | None = None,
                  location: str = "MG Road, Bengaluru") -> dict:
    resp = client.post(
        "/centres", headers=admin_headers,
        json={"name": name or f"Centre {uuid.uuid4().hex[:6]}", "location": location},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def add_offering(client, admin_headers, centre_id: int, test_id: int, price: str = "500.00") -> dict:
    resp = client.post(
        f"/centres/{centre_id}/offerings", headers=admin_headers,
        json={"test_id": test_id, "price": price},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_centre_with_test(client, admin_headers, price: str = "500.00") -> dict:
    test = create_test(client, admin_headers)
    centre = create_centre(client, admin_headers)
    offering = add_offering(client, admin_headers, centre["id"], test["id"], price)
    return {"centre": centre, "test": test, "offering": offering}


def future_iso(days: int = 2, hour: int = 10) -> str:
    when = (datetime.now(timezone.utc) + timedelta(days=days)).replace(
        hour=hour, minute=30, second=0, microsecond=0
    )
    return when.isoformat()


def create_booking(client, user_headers, centre_id: int, test_id: int,
                   when: str | None = None) -> dict:
    resp = client.post(
        "/bookings", headers=user_headers,
        json={"centre_id": centre_id, "test_id": test_id,
              "appointment_at": when or future_iso()},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def pay_for_booking(client, user_headers, booking_id: int,
                    simulate: str | None = None) -> dict:
    body = {"booking_id": booking_id}
    if simulate:
        body["simulate_outcome"] = simulate
    resp = client.post("/payments", headers=user_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def sign_webhook(body: bytes, secret: str = "test-webhook-secret") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def webhook_body(event_id: str, payment_reference: str, status: str = "SUCCESS") -> bytes:
    import json

    return json.dumps(
        {"event_id": event_id, "payment_reference": payment_reference, "status": status}
    ).encode()
