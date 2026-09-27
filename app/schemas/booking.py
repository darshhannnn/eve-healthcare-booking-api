from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.booking import BookingStatus
from app.schemas.catalog import TestOut
from app.schemas.common import UtcDatetime, money


class CentreBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TestBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class BookingCreate(BaseModel):
    centre_id: int = Field(gt=0)
    test_id: int = Field(gt=0)
    # Naive timestamps are interpreted as UTC (see UtcDatetime).
    appointment_at: UtcDatetime = Field(examples=["2026-10-05T09:30:00Z"])


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    centre: CentreBrief
    test: TestBrief
    appointment_at: UtcDatetime
    amount: Decimal
    status: BookingStatus
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return money(value)


class BookingCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)
