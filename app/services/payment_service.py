"""Payment use-cases: the mock gateway call and idempotent webhook handling.

Flow (documented assumption): the mock gateway resolves synchronously, so
POST /payments returns SUCCESS/FAILED and updates the booking immediately.
The webhook endpoint then acts as the *provider-driven* channel (retries,
confirmations, provider-initiated status events). Its contract is strictly
idempotent:

* unknown ``event_id``  -> processed once, recorded in ``webhook_events``
* repeated ``event_id`` -> 200 "duplicate", no state change (unique constraint
  also protects against two concurrent deliveries of the same event)
* unknown payment ref   -> 404, event stored as UNMATCHED for admin retry
* status already set    -> no-op, recorded
* conflicting status    -> IGNORED (first terminal state wins)
* cancelled booking     -> IGNORED (a cancelled booking is never resurrected)
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.time import utcnow
from app.models.booking import Booking, BookingStatus
from app.models.payment import Payment, PaymentStatus, WebhookEvent, WebhookEventStatus
from app.models.user import User, UserRole
from app.schemas.payment import WebhookPayload
from app.utils.idempotency import request_fingerprint


def create_payment(
    db: Session,
    user: User,
    booking_id: int,
    simulate_outcome: str | None,
    idempotency_key: str | None,
) -> tuple[Payment, bool]:
    """Charge a PENDING booking through the mock gateway.

    Returns ``(payment, replayed)`` — ``replayed`` is True when an
    ``Idempotency-Key`` previously seen (scoped to the booking's owner) is
    satisfied from the store instead of charging again. A replayed key with a
    *different* request payload is rejected Stripe-style rather than replayed.
    """
    # Row lock so two concurrent payments cannot both observe PENDING (PG).
    # SQLite (dev/tests) ignores FOR UPDATE and is protected by the checks below.
    booking = db.get(Booking, booking_id, with_for_update=True)
    if booking is None:
        raise NotFoundError("Booking not found")
    if booking.user_id != user.id and user.role != UserRole.ADMIN.value:
        raise ForbiddenError("You cannot pay for another user's booking")

    # Canonicalise the outcome so an omitted field and "success" fingerprint
    # identically; booking_id pins the replay to the same target.
    fingerprint = request_fingerprint(booking_id, simulate_outcome or "success")

    # Satisfy replays before state checks so a retry after a successful
    # payment returns the original payment instead of a conflict.
    if idempotency_key:
        existing = db.scalar(
            select(Payment).where(
                Payment.user_id == booking.user_id,
                Payment.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ConflictError(
                    "This Idempotency-Key was already used with a different request payload"
                )
            return existing, True

    if booking.status != BookingStatus.PENDING.value:
        raise ConflictError(f"Booking is {booking.status}; only PENDING bookings can be paid")

    outcome = PaymentStatus.FAILED if simulate_outcome == "failure" else PaymentStatus.SUCCESS
    payment = Payment(
        user_id=booking.user_id,
        booking_id=booking.id,
        amount=booking.amount,
        status=outcome.value,
        provider_reference=f"pay_{uuid.uuid4().hex}",
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
    )
    booking.status = (
        BookingStatus.CONFIRMED.value if outcome is PaymentStatus.SUCCESS
        else BookingStatus.FAILED.value
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        # The only unique constraint this INSERT can violate is
        # (user_id, idempotency_key): a concurrent retry of the same key.
        db.rollback()
        if not idempotency_key:
            raise
        replay = db.scalar(
            select(Payment).where(
                Payment.user_id == booking.user_id,
                Payment.idempotency_key == idempotency_key,
            )
        )
        if replay is None:
            raise
        if replay.request_fingerprint != fingerprint:
            raise ConflictError(
                "This Idempotency-Key was already used with a different request payload"
            )
        return replay, True
    db.refresh(payment)
    return payment, False


def handle_webhook(db: Session, payload: WebhookPayload) -> dict:
    """Apply a provider event exactly once. Always record the delivery."""
    existing = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == payload.event_id))
    if existing is not None:
        return {
            "result": "duplicate",
            "detail": f"Event '{payload.event_id}' was already received; no changes made.",
        }

    payment = db.scalar(
        select(Payment)
        .where(Payment.provider_reference == payload.payment_reference)
        .options(selectinload(Payment.booking))
    )
    if payment is None:
        event = WebhookEvent(
            event_id=payload.event_id,
            payment_id=None,
            status=WebhookEventStatus.UNMATCHED.value,
            payload=payload.model_dump(mode="json"),
            detail=f"No payment with provider reference '{payload.payment_reference}'",
        )
        db.add(event)
        _commit_webhook(db, payload.event_id)
        raise NotFoundError(
            f"Webhook references unknown payment '{payload.payment_reference}'"
        )

    booking: Booking | None = payment.booking
    if booking is not None and booking.status == BookingStatus.CANCELLED.value:
        event_status, detail = (
            WebhookEventStatus.IGNORED,
            "Booking already cancelled; payment update ignored.",
        )
    elif payment.status == payload.status:
        event_status, detail = (
            WebhookEventStatus.PROCESSED,
            f"Payment already {payment.status}; no state change.",
        )
    else:
        event_status, detail = (
            WebhookEventStatus.IGNORED,
            f"Payment already {payment.status}; conflicting '{payload.status}' event ignored.",
        )

    event = WebhookEvent(
        event_id=payload.event_id,
        payment_id=payment.id,
        status=event_status.value,
        payload=payload.model_dump(mode="json"),
        detail=detail,
        processed_at=utcnow(),
    )
    db.add(event)
    _commit_webhook(db, payload.event_id)
    return {"result": event_status.value.lower(), "detail": detail}


def retry_webhook_event(db: Session, event_row_id: int) -> dict:
    """Admin action: re-run a stored event (e.g. one that was UNMATCHED)."""
    event = db.get(WebhookEvent, event_row_id)
    if event is None:
        raise NotFoundError("Webhook event not found")
    if event.status == WebhookEventStatus.PROCESSED.value:
        return {"event_id": event.event_id, "result": "already_processed", "detail": event.detail}

    reference = (event.payload or {}).get("payment_reference")
    payment = db.scalar(select(Payment).where(Payment.provider_reference == reference))
    if payment is None:
        return {
            "event_id": event.event_id,
            "result": "still_unmatched",
            "detail": "No matching payment yet; event kept for later retries.",
        }

    event.payment_id = payment.id
    event.status = WebhookEventStatus.PROCESSED.value
    event.detail = "Payment matched on retry; already in a terminal state — no state change."
    event.processed_at = utcnow()
    db.commit()
    return {"event_id": event.event_id, "result": "processed", "detail": event.detail}


def list_payments(
    db: Session,
    user: User,
    booking_id: int | None,
    page: int,
    page_size: int,
) -> tuple[list[Payment], int]:
    filters = []
    if user.role != UserRole.ADMIN.value:
        filters.append(Payment.booking.has(Booking.user_id == user.id))
    if booking_id is not None:
        filters.append(Payment.booking_id == booking_id)

    total = db.scalar(select(func.count()).select_from(Payment).where(*filters)) or 0
    items = db.execute(
        select(Payment)
        .where(*filters)
        .order_by(Payment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return list(items), int(total)


def get_payment_for_user(db: Session, payment_id: int, user: User) -> Payment:
    payment = db.scalar(
        select(Payment).where(Payment.id == payment_id).options(selectinload(Payment.booking))
    )
    if payment is None:
        raise NotFoundError("Payment not found")
    booking: Booking | None = payment.booking
    owner_id = booking.user_id if booking is not None else None
    if owner_id != user.id and user.role != UserRole.ADMIN.value:
        raise ForbiddenError("You do not have access to this payment")
    return payment


def _commit_webhook(db: Session, event_id: str) -> None:
    """Commit, treating a unique-constraint loss on ``event_id`` as a
    concurrent duplicate delivery (idempotent no-op)."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError(
            f"Event '{event_id}' was processed concurrently; treat as duplicate."
        )
