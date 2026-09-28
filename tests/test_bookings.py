"""Booking rules: ownership, validation, slots, cancellation."""

import pytest

from app.core.config import get_settings

_ON_POSTGRES = get_settings().DATABASE_URL.startswith(("postgres", "postgresql"))


def test_create_booking_success_snapshots_amount(client):
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers, price="649.00")

    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])
    assert booking["status"] == "PENDING"
    assert booking["amount"] == "649.00"
    assert booking["user_id"] == user.id
    assert booking["centre"]["id"] == data["centre"]["id"]
    assert booking["test"]["code"] == data["test"]["code"]


def test_booking_requires_auth(client):
    resp = client.post(
        "/bookings",
        json={"centre_id": 1, "test_id": 1, "appointment_at": "2030-01-01T10:00:00Z"},
    )
    assert resp.status_code == 401


def test_booking_unknown_centre_404(client):
    from tests.helpers import make_user

    user = make_user(client)
    resp = client.post(
        "/bookings", headers=user.headers,
        json={"centre_id": 99999, "test_id": 1, "appointment_at": "2030-01-01T10:00:00Z"},
    )
    assert resp.status_code == 404


def test_booking_unknown_test_404(client):
    from tests.helpers import admin_user, create_centre, make_user

    admin = admin_user(client)
    centre = create_centre(client, admin.headers)
    user = make_user(client)
    resp = client.post(
        "/bookings", headers=user.headers,
        json={"centre_id": centre["id"], "test_id": 99999,
              "appointment_at": "2030-01-01T10:00:00Z"},
    )
    assert resp.status_code == 404


def test_booking_test_not_offered_at_centre_422(client):
    from tests.helpers import admin_user, create_centre, create_test, make_user

    admin = admin_user(client)
    centre = create_centre(client, admin.headers)  # no offerings
    test = create_test(client, admin.headers)
    user = make_user(client)
    resp = client.post(
        "/bookings", headers=user.headers,
        json={"centre_id": centre["id"], "test_id": test["id"],
              "appointment_at": "2030-01-01T10:00:00Z"},
    )
    assert resp.status_code == 422
    assert "not offered" in resp.json()["detail"].lower()


def test_booking_past_appointment_422(client):
    from tests.helpers import admin_user, make_centre_with_test, make_user

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    resp = client.post(
        "/bookings", headers=user.headers,
        json={"centre_id": data["centre"]["id"], "test_id": data["test"]["id"],
              "appointment_at": "2001-01-01T10:00:00Z"},
    )
    assert resp.status_code == 422
    assert "future" in resp.json()["detail"].lower()


def test_booking_naive_datetime_treated_as_utc(client):
    """A naive timestamp is accepted and interpreted as UTC (documented assumption)."""
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking, future_iso

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    naive = future_iso().replace("+00:00", "")
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"],
                             when=naive)
    # Output is normalised to UTC ("Z" suffix) even though input was naive.
    assert booking["appointment_at"].endswith(("Z", "+00:00"))
    assert booking["appointment_at"][:19] == naive[:19]


def test_booking_duplicate_slot_409(client):
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking, future_iso

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    when = future_iso()
    create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"], when=when)
    resp = client.post(
        "/bookings", headers=user.headers,
        json={"centre_id": data["centre"]["id"], "test_id": data["test"]["id"],
              "appointment_at": when},
    )
    assert resp.status_code == 409


def test_booking_idempotency_key_replay_returns_same_booking(client):
    """A retried POST /bookings with the same Idempotency-Key returns the
    original booking (200) instead of a 409 — mirroring POST /payments."""
    from tests.helpers import admin_user, make_centre_with_test, make_user, future_iso

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    body = {"centre_id": data["centre"]["id"], "test_id": data["test"]["id"],
            "appointment_at": future_iso()}

    first = client.post(
        "/bookings", headers={**user.headers, "Idempotency-Key": "booking-retry-1"}, json=body
    )
    assert first.status_code == 201

    second = client.post(
        "/bookings", headers={**user.headers, "Idempotency-Key": "booking-retry-1"}, json=body
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_booking_idempotency_key_reusable_across_users(client):
    """Keys are scoped per user (composite unique on user_id + key), so one
    user's key never collides with — or leaks information about — another's."""
    from tests.helpers import admin_user, make_centre_with_test, make_user, future_iso

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers)
    user_a = make_user(client)
    user_b = make_user(client)
    body = {"centre_id": data["centre"]["id"], "test_id": data["test"]["id"],
            "appointment_at": future_iso()}

    first = client.post(
        "/bookings", headers={**user_a.headers, "Idempotency-Key": "shared-key"}, json=body
    )
    assert first.status_code == 201

    second = client.post(
        "/bookings", headers={**user_b.headers, "Idempotency-Key": "shared-key"}, json=body
    )
    assert second.status_code == 201  # independent booking, not a replay
    assert second.json()["id"] != first.json()["id"]


def test_booking_idempotency_replay_with_different_payload_conflicts(client):
    """Stripe-style: the same key with a different request must be rejected,
    not silently answered with the original booking."""
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking, future_iso

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)

    first = client.post(
        "/bookings", headers={**user.headers, "Idempotency-Key": "key-mismatch"},
        json={"centre_id": data["centre"]["id"], "test_id": data["test"]["id"],
              "appointment_at": future_iso(days=2)},
    )
    assert first.status_code == 201

    second = client.post(
        "/bookings", headers={**user.headers, "Idempotency-Key": "key-mismatch"},
        json={"centre_id": data["centre"]["id"], "test_id": data["test"]["id"],
              "appointment_at": future_iso(days=3)},  # different request, same key
    )
    assert second.status_code == 409
    assert "different request payload" in second.json()["detail"]


@pytest.mark.skipif(
    not _ON_POSTGRES,
    reason="FOR UPDATE row locking is a no-op on SQLite (the suite's default DB); "
    "this test runs for real in the CI 'test-postgres' job, where the suite "
    "executes against PostgreSQL",
)
def test_concurrent_duplicate_slot_creates_single_booking(client):
    """Documents the concurrency guarantee: N simultaneous bookings for the
    same user/centre/test/slot must produce exactly one 201."""
    from concurrent.futures import ThreadPoolExecutor

    from tests.helpers import admin_user, make_centre_with_test, make_user, future_iso

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    body = {"centre_id": data["centre"]["id"], "test_id": data["test"]["id"],
            "appointment_at": future_iso()}

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(lambda _: client.post("/bookings", headers=user.headers, json=body), range(4))
        )
    assert sum(r.status_code == 201 for r in responses) == 1
    assert sum(r.status_code == 409 for r in responses) == 3


def test_booking_rebook_after_cancel_allowed(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, future_iso,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    when = future_iso()
    first = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"], when=when)
    client.post(f"/bookings/{first['id']}/cancel", headers=user.headers)

    resp = client.post(
        "/bookings", headers=user.headers,
        json={"centre_id": data["centre"]["id"], "test_id": data["test"]["id"],
              "appointment_at": when},
    )
    assert resp.status_code == 201


def test_list_bookings_only_own(client):
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers)
    user_a = make_user(client)
    user_b = make_user(client)
    create_booking(client, user_a.headers, data["centre"]["id"], data["test"]["id"])
    create_booking(client, user_b.headers, data["centre"]["id"], data["test"]["id"])

    resp = client.get("/bookings", headers=user_a.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["user_id"] == user_a.id

    resp_b = client.get("/bookings", headers=user_b.headers)
    assert resp_b.json()["total"] == 1
    assert resp_b.json()["items"][0]["user_id"] == user_b.id


def test_status_filter(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
        future_iso,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    paid = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])
    create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"],
                   when=future_iso(days=3))
    pay_for_booking(client, user.headers, paid["id"])

    resp = client.get("/bookings", headers=user.headers, params={"status": "CONFIRMED"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "CONFIRMED"


def test_non_owner_cannot_read_or_cancel_booking(client):
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers)
    owner = make_user(client)
    intruder = make_user(client)
    booking = create_booking(client, owner.headers, data["centre"]["id"], data["test"]["id"])

    assert client.get(f"/bookings/{booking['id']}", headers=intruder.headers).status_code == 403
    assert (
        client.post(f"/bookings/{booking['id']}/cancel", headers=intruder.headers).status_code
        == 403
    )


def test_admin_can_read_any_booking(client):
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers)
    owner = make_user(client)
    booking = create_booking(client, owner.headers, data["centre"]["id"], data["test"]["id"])
    resp = client.get(f"/bookings/{booking['id']}", headers=admin.headers)
    assert resp.status_code == 200


def test_admin_sees_all_bookings_in_list(client):
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers)
    for _ in range(2):
        user = make_user(client)
        create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])

    resp = client.get("/bookings", headers=admin.headers)
    assert resp.status_code == 200 and resp.json()["total"] == 2


def test_cancel_pending_then_cancel_again_conflict(client):
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])

    resp = client.post(f"/bookings/{booking['id']}/cancel", headers=user.headers)
    assert resp.status_code == 200 and resp.json()["status"] == "CANCELLED"

    resp = client.post(f"/bookings/{booking['id']}/cancel", headers=user.headers)
    assert resp.status_code == 409


def test_cancel_confirmed_booking_allowed(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])
    pay_for_booking(client, user.headers, booking["id"])

    resp = client.post(f"/bookings/{booking['id']}/cancel", headers=user.headers)
    assert resp.status_code == 200 and resp.json()["status"] == "CANCELLED"


def test_cancelled_booking_cannot_be_paid(client):
    from tests.helpers import admin_user, make_centre_with_test, make_user, create_booking

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])
    client.post(f"/bookings/{booking['id']}/cancel", headers=user.headers)

    resp = client.post("/payments", headers=user.headers, json={"booking_id": booking["id"]})
    assert resp.status_code == 409
