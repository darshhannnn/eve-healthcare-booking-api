from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.booking import BookingStatus
from app.models.payment import PaymentStatus
from app.schemas.common import UtcDatetime, money


class PaymentCreate(BaseModel):
    booking_id: int = Field(gt=0)
    simulate_outcome: Literal["success", "failure"] | None = Field(
        default=None,
        description="Force the mock gateway's result. Omitted => success. "
        "This stands in for real card/gateway behaviour.",
    )


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: int
    provider_reference: str
    amount: Decimal
    status: PaymentStatus
    created_at: UtcDatetime

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return money(value)


class PaymentResult(PaymentOut):
    """Payment plus the resulting booking status, so clients can update
    their UI without a second call."""

    booking_status: BookingStatus


class WebhookPayload(BaseModel):
    """Body of POST /payments/webhook — what the (simulated) provider sends."""

    event_id: str = Field(min_length=4, max_length=120, examples=["evt_2c9a8f41"])
    payment_reference: str = Field(min_length=6, max_length=64, examples=["pay_9f2c41aa"])
    status: Literal["SUCCESS", "FAILED"]
    timestamp: UtcDatetime | None = None


class WebhookAck(BaseModel):
    received: bool = True
    event_id: str
    result: str
    detail: str | None = None


class WebhookEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    payment_id: int | None
    status: str
    payload: dict
    detail: str | None
    received_at: UtcDatetime
    processed_at: UtcDatetime | None
