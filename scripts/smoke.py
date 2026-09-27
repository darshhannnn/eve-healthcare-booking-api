"""End-to-end smoke test against a running server.

Usage:
    python scripts/smoke.py [base_url]

Defaults to http://localhost:8000. Walks the whole happy path:
signup -> login -> admin seeds centre/test/price -> browse -> book -> pay
-> webhook duplicate delivery -> cancel.
"""

import hashlib
import hmac
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
# Must match WEBHOOK_SECRET of the running server (docker-compose default).
WEBHOOK_SECRET = "whsec_local_dev"

ok_count = 0


def ok(label: str, condition: bool, extra: str = "") -> None:
    global ok_count
    if not condition:
        print(f"FAIL  {label} {extra}")
        sys.exit(1)
    ok_count += 1
    print(f"ok    {label}")


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15)

    r = client.get("/health")
    ok("health", r.status_code == 200, r.text)

    email = f"smoke_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/auth/signup",
        json={"email": email, "password": "Str0ngPass!23", "full_name": "Smoke Tester"},
    )
    ok("signup", r.status_code == 201, r.text)

    r = client.post("/auth/login", json={"email": email, "password": "Str0ngPass!23"})
    ok("login", r.status_code == 200, r.text)
    user_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "Admin@12345"},
    )
    ok("admin login", r.status_code == 200, r.text)
    admin_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    code = f"SMK{uuid.uuid4().hex[:6].upper()}"
    r = client.post("/tests", headers=admin_h, json={"code": code, "name": "Smoke Panel"})
    ok("create test", r.status_code == 201, r.text)
    test_id = r.json()["id"]

    r = client.post(
        "/centres", headers=admin_h, json={"name": "Smoke Centre", "location": "Bengaluru"}
    )
    ok("create centre", r.status_code == 201, r.text)
    centre_id = r.json()["id"]

    r = client.post(
        f"/centres/{centre_id}/offerings", headers=admin_h, json={"test_id": test_id, "price": "499.00"}
    )
    ok("add offering", r.status_code == 201, r.text)

    r = client.get(f"/centres/{centre_id}")
    ok("centre detail with offerings", r.status_code == 200 and r.json()["offerings"], r.text)

    appointment = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    r = client.post(
        "/bookings",
        headers=user_h,
        json={"centre_id": centre_id, "test_id": test_id, "appointment_at": appointment},
    )
    ok("create booking", r.status_code == 201, r.text)
    booking = r.json()
    ok("booking amount snapshot", booking["amount"] == "499.00", booking["amount"])
    ok("booking pending", booking["status"] == "PENDING", booking["status"])

    r = client.post("/payments", headers=user_h, json={"booking_id": booking["id"]})
    ok("payment success", r.status_code == 201 and r.json()["status"] == "SUCCESS", r.text)
    payment = r.json()
    ok("booking confirmed", payment["booking_status"] == "CONFIRMED")

    # Idempotent webhook: deliver twice, expect duplicate on the second.
    event = json.dumps(
        {
            "event_id": f"evt_{uuid.uuid4().hex[:10]}",
            "payment_reference": payment["provider_reference"],
            "status": "SUCCESS",
        }
    ).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), event, hashlib.sha256).hexdigest()
    r = client.post(
        "/payments/webhook", content=event, headers={"X-EVE-Signature": sig}
    )
    ok("webhook processed", r.status_code == 200 and r.json()["result"] == "processed", r.text)
    r = client.post(
        "/payments/webhook", content=event, headers={"X-EVE-Signature": sig}
    )
    ok("webhook duplicate is no-op", r.status_code == 200 and r.json()["result"] == "duplicate", r.text)

    r = client.post(f"/bookings/{booking['id']}/cancel", headers=user_h)
    ok("cancel booking", r.status_code == 200 and r.json()["status"] == "CANCELLED", r.text)

    print(f"\nAll {ok_count} smoke checks passed.")


if __name__ == "__main__":
    main()
