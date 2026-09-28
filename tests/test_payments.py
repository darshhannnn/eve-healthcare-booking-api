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


def test_payment_idempotency_key_reusable_across_users(client):
    """Keys are scoped to the booking's owner — different users can reuse the
    same key without colliding or learning anything about each other."""
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking,
    )

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers)
    owner_a = make_user(client)
    owner_b = make_user(client)
    b_a = create_booking(client, owner_a.headers, data["centre"]["id"], data["test"]["id"])
    b_b = create_booking(client, owner_b.headers, data["centre"]["id"], data["test"]["id"])

    first = client.post(
        "/payments", headers={**owner_a.headers, "Idempotency-Key": "shared-pay"},
        json={"booking_id": b_a["id"]},
    )
    second = client.post(
        "/payments", headers={**owner_b.headers, "Idempotency-Key": "shared-pay"},
        json={"booking_id": b_b["id"]},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]


def test_payment_idempotency_replay_with_different_payload_conflicts(client):
    """Stripe-style: the same key aimed at a different booking is rejected."""
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, future_iso,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    b1 = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])
    b2 = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"],
                        when=future_iso(days=3))

    first = client.post(
        "/payments", headers={**user.headers, "Idempotency-Key": "pay-mismatch"},
        json={"booking_id": b1["id"]},
    )
    assert first.status_code == 201

    second = client.post(
        "/payments", headers={**user.headers, "Idempotency-Key": "pay-mismatch"},
        json={"booking_id": b2["id"]},
    )
    assert second.status_code == 409
    assert "different request payload" in second.json()["detail"]


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


def test_spec_trailing_slash_paths_answer_directly(client):
    """The assignment spec writes POST /payments/ and POST /payments/webhook/
    with trailing slashes — those exact paths must return real responses, not
    307 redirects that curl won't follow."""
    import hmac as hmac_mod

    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking,
        sign_webhook, webhook_body,
    )
    from app.core.config import get_settings

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])

    resp = client.post(
        "/payments/", headers=user.headers,
        json={"booking_id": booking["id"]},
        follow_redirects=False,
    )
    assert resp.status_code == 201  # a 307 would mean only the bare path exists

    body = webhook_body("evt_slash_path", resp.json()["provider_reference"], "SUCCESS")
    sig = sign_webhook(body, get_settings().WEBHOOK_SECRET)
    resp = client.post(
        "/payments/webhook/", content=body,
        headers={"X-EVE-Signature": sig},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert resp.json()["event_id"] == "evt_slash_path"
