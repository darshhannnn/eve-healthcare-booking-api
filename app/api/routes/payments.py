"""Payment endpoints: the mock gateway charge and the provider webhook."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_pagination
from app.core.config import get_settings
from app.core.exceptions import UnauthenticatedError, UnprocessableError
from app.core.security import webhook_signature
from app.db.session import get_db
from app.models.booking import BookingStatus
from app.models.user import User
from app.schemas.common import Page
from app.schemas.payment import (
    PaymentCreate,
    PaymentOut,
    PaymentResult,
    WebhookAck,
    WebhookPayload,
)
from app.services import payment_service

router = APIRouter()


@router.post(
    "/payments",
    response_model=PaymentResult,
    status_code=status.HTTP_201_CREATED,
    summary="Pay for a PENDING booking through the mock gateway (auth)",
)
def create_payment(
    payload: PaymentCreate,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            max_length=120,
            description="Send the same key to safely retry this call; the "
            "original payment is returned instead of charging twice.",
        ),
    ] = None,
) -> PaymentResult:
    payment, replayed = payment_service.create_payment(
        db, user, payload.booking_id, payload.simulate_outcome, idempotency_key or None
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
    return PaymentResult(
        id=payment.id,
        booking_id=payment.booking_id,
        provider_reference=payment.provider_reference,
        amount=payment.amount,
        status=payment.status,
        created_at=payment.created_at,
        booking_status=BookingStatus(payment.booking.status),
    )


@router.get(
    "/payments",
    response_model=Page[PaymentOut],
    summary="List payments (own; admins see all)",
)
def list_payments(
    booking_id: int | None = Query(default=None, gt=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pagination: tuple[int, int] = Depends(get_pagination),
) -> Page[PaymentOut]:
    page, page_size = pagination
    items, total = payment_service.list_payments(db, user, booking_id, page, page_size)
    return Page[PaymentOut].build(
        [PaymentOut.model_validate(p) for p in items], total, page, page_size
    )


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentOut,
    summary="Payment detail (owner or admin)",
)
def get_payment(
    payment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    payment = payment_service.get_payment_for_user(db, payment_id, user)
    return PaymentOut.model_validate(payment)


@router.post(
    "/payments/webhook",
    response_model=WebhookAck,
    summary="Simulated provider webhook — idempotent payment-status updates",
    description=(
        "Accepts payment-status events from the (simulated) payment provider. "
        "Replay-safe: the same `event_id` never applies twice, conflicting or "
        "late events are recorded but ignored, and unknown payment references "
        "are stored for admin retry."
    ),
)
async def payment_webhook(request: Request, db: Session = Depends(get_db)) -> WebhookAck:
    raw_body = await request.body()

    settings = get_settings()
    if settings.WEBHOOK_SECRET:
        signature = request.headers.get("X-EVE-Signature")
        expected = webhook_signature(raw_body, settings.WEBHOOK_SECRET)
        if not signature or signature.lower() != expected:
            raise UnauthenticatedError("Missing or invalid webhook signature")

    try:
        payload = WebhookPayload.model_validate_json(raw_body)
    except ValidationError:
        raise UnprocessableError("Invalid webhook payload")

    result = payment_service.handle_webhook(db, payload)
    return WebhookAck(
        received=True,
        event_id=payload.event_id,
        result=result["result"],
        detail=result.get("detail"),
    )
