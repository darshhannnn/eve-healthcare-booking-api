"""Mock gateway payments: outcomes, authorisation, idempotency keys."""


def test_payment_success_confirms_booking(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers, price="299.00")
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])

    payment = pay_for_booking(client, user.headers, booking["id"])
    assert payment["status"] == "SUCCESS"
    assert payment["booking_status"] == "CONFIRMED"
    assert payment["amount"] == "299.00"
    assert payment["provider_reference"].startswith("pay_")

    detail = client.get(f"/bookings/{booking['id']}", headers=user.headers).json()
    assert detail["status"] == "CONFIRMED"


def test_payment_simulated_failure_fails_booking(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])

    payment = pay_for_booking(client, user.headers, booking["id"], simulate="failure")
    assert payment["status"] == "FAILED"
    assert payment["booking_status"] == "FAILED"

    detail = client.get(f"/bookings/{booking['id']}", headers=user.headers).json()
    assert detail["status"] == "FAILED"


def test_payment_requires_auth(client):
    assert client.post("/payments", json={"booking_id": 1}).status_code == 401


def test_payment_unknown_booking_404(client):
    from tests.helpers import make_user

    user = make_user(client)
    resp = client.post("/payments", headers=user.headers, json={"booking_id": 99999})
    assert resp.status_code == 404


def test_payment_for_others_booking_403(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking,
    )

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers)
    owner = make_user(client)
    stranger = make_user(client)
    booking = create_booking(client, owner.headers, data["centre"]["id"], data["test"]["id"])

    resp = client.post("/payments", headers=stranger.headers, json={"booking_id": booking["id"]})
    assert resp.status_code == 403


def test_payment_twice_conflict_409(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])

    pay_for_booking(client, user.headers, booking["id"])
    resp = client.post("/payments", headers=user.headers, json={"booking_id": booking["id"]})
    assert resp.status_code == 409
    assert "only PENDING" in resp.json()["detail"]


def test_payment_on_failed_booking_conflict(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])
    pay_for_booking(client, user.headers, booking["id"], simulate="failure")

    resp = client.post("/payments", headers=user.headers, json={"booking_id": booking["id"]})
    assert resp.status_code == 409


def test_idempotency_key_replay_returns_same_payment(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])

    first = client.post(
        "/payments", headers={**user.headers, "Idempotency-Key": "order-abc-123"},
        json={"booking_id": booking["id"]},
    )
    assert first.status_code == 201
    second = client.post(
        "/payments", headers={**user.headers, "Idempotency-Key": "order-abc-123"},
        json={"booking_id": booking["id"]},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["provider_reference"] == first.json()["provider_reference"]


def test_idempotency_key_scoped_per_payment(client):
    """A key that was never used must not be treated as a replay."""
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    b1 = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])

    resp = client.post(
        "/payments", headers={**user.headers, "Idempotency-Key": "fresh-key-1"},
        json={"booking_id": b1["id"]},
    )
    assert resp.status_code == 201


def test_payment_listing_owner_only(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
    )

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers)
    owner = make_user(client)
    stranger = make_user(client)
    booking = create_booking(client, owner.headers, data["centre"]["id"], data["test"]["id"])
    pay_for_booking(client, owner.headers, booking["id"])

    assert client.get("/payments", headers=owner.headers).json()["total"] == 1
    assert client.get("/payments", headers=stranger.headers).json()["total"] == 0

    detail = client.get("/payments", headers=owner.headers).json()["items"][0]
    assert client.get(f"/payments/{detail['id']}", headers=stranger.headers).status_code == 403
    assert client.get(f"/payments/{detail['id']}", headers=admin.headers).status_code == 200
