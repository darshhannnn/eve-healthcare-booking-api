"""Webhook contract: signatures, idempotency, conflicting/unmatched events."""

from tests.helpers import sign_webhook, webhook_body


def post_webhook(client, body: bytes, sign: bool = True, secret: str = "test-webhook-secret",
                 signature: str | None = None):
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["X-EVE-Signature"] = signature or sign_webhook(body, secret)
    return client.post("/payments/webhook", content=body, headers=headers)


def test_webhook_missing_signature_401(client):
    from tests.helpers import webhook_body

    resp = post_webhook(client, webhook_body("evt_no_sig", "pay_unknown"), sign=False)
    assert resp.status_code == 401


def test_webhook_bad_signature_401(client):
    from tests.helpers import webhook_body

    resp = post_webhook(
        client, webhook_body("evt_bad_sig", "pay_unknown"),
        signature="00" * 32,
    )
    assert resp.status_code == 401


def test_webhook_invalid_payload_signed_422(client):
    resp = post_webhook(client, b'{"event_id": "x"}')  # missing fields
    assert resp.status_code == 422


def test_webhook_unknown_payment_reference_404_and_stored(client, db_engine):
    from sqlalchemy.orm import Session

    from app.models.payment import WebhookEvent, WebhookEventStatus
    from tests.helpers import webhook_body

    body = webhook_body("evt_unmatched", "pay_missing123")
    resp = post_webhook(client, body)
    assert resp.status_code == 404

    with Session(bind=db_engine) as db:
        event = db.query(WebhookEvent).filter_by(event_id="evt_unmatched").one()
        assert event.status == WebhookEventStatus.UNMATCHED.value


def test_webhook_duplicate_delivery_is_idempotent(client, db_engine):
    from sqlalchemy.orm import Session

    from app.models.payment import Payment, WebhookEvent
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
        webhook_body,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])
    payment = pay_for_booking(client, user.headers, booking["id"])

    body = webhook_body("evt_dup_001", payment["provider_reference"], "SUCCESS")
    first = post_webhook(client, body)
    assert first.status_code == 200
    assert first.json()["result"] == "processed"

    second = post_webhook(client, body)
    assert second.status_code == 200
    assert second.json()["result"] == "duplicate"

    with Session(bind=db_engine) as db:
        assert db.query(Payment).count() == 1  # no duplicate payment
        assert db.query(WebhookEvent).filter_by(event_id="evt_dup_001").count() == 1

    # booking state untouched by the replays
    detail = client.get(f"/bookings/{booking['id']}", headers=user.headers).json()
    assert detail["status"] == "CONFIRMED"


def test_webhook_conflicting_status_ignored(client, db_engine):
    from sqlalchemy.orm import Session

    from app.models.payment import WebhookEvent, WebhookEventStatus
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
        webhook_body,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])
    payment = pay_for_booking(client, user.headers, booking["id"])  # SUCCESS

    body = webhook_body("evt_conflict", payment["provider_reference"], "FAILED")
    resp = post_webhook(client, body)
    assert resp.status_code == 200
    assert resp.json()["result"] == "ignored"

    with Session(bind=db_engine) as db:
        event = db.query(WebhookEvent).filter_by(event_id="evt_conflict").one()
        assert event.status == WebhookEventStatus.IGNORED.value

    detail = client.get(f"/bookings/{booking['id']}", headers=user.headers).json()
    assert detail["status"] == "CONFIRMED"  # never flipped to FAILED


def test_webhook_on_cancelled_booking_ignored(client):
    from tests.helpers import (
        admin_user, make_centre_with_test, make_user, create_booking, pay_for_booking,
        webhook_body,
    )

    admin = admin_user(client)
    user = make_user(client)
    data = make_centre_with_test(client, admin.headers)
    booking = create_booking(client, user.headers, data["centre"]["id"], data["test"]["id"])
    payment = pay_for_booking(client, user.headers, booking["id"])
    client.post(f"/bookings/{booking['id']}/cancel", headers=user.headers)

    body = webhook_body("evt_after_cancel", payment["provider_reference"], "SUCCESS")
    resp = post_webhook(client, body)
    assert resp.status_code == 200
    assert resp.json()["result"] == "ignored"

    detail = client.get(f"/bookings/{booking['id']}", headers=user.headers).json()
    assert detail["status"] == "CANCELLED"


def test_webhook_no_secret_configured_accepts_unsigned(client, monkeypatch):
    from app.core.config import get_settings
    from tests.helpers import webhook_body

    monkeypatch.setattr(get_settings(), "WEBHOOK_SECRET", "")
    resp = post_webhook(client, webhook_body("evt_open", "pay_whatever"), sign=False)
    assert resp.status_code == 404  # passes auth, then fails to match a payment


def test_admin_lists_webhook_events_and_retries(client):
    from tests.helpers import admin_user, make_user, webhook_body

    admin = admin_user(client)
    user = make_user(client)

    # an unmatched event + a signed duplicate attempt
    post_webhook(client, webhook_body("evt_list_1", "pay_missing123"))

    resp = client.get("/admin/webhook-events", headers=admin.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "UNMATCHED"

    # non-admins are locked out
    assert client.get("/admin/webhook-events", headers=user.headers).status_code == 403

    # retry of a PROCESSED event is a no-op; retry of UNMATCHED stays unmatched
    event_row_id = body["items"][0]["id"]
    retry = client.post(f"/admin/webhook-events/{event_row_id}/retry", headers=admin.headers)
    assert retry.status_code == 200
    assert retry.json()["result"] == "still_unmatched"

    unknown = client.post("/admin/webhook-events/99999/retry", headers=admin.headers)
    assert unknown.status_code == 404
