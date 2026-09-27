from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas.common import UtcDatetime, money


class CentreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["EVE Diagnostics — Indiranagar"])
    location: str = Field(min_length=1, max_length=200, examples=["12, 100ft Road, Bengaluru"])


class CentreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, min_length=1, max_length=200)


class CentreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str
    created_at: UtcDatetime


class TestCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40, examples=["CBC"])
    name: str = Field(min_length=1, max_length=120, examples=["Complete Blood Count"])
    description: str | None = None

    @field_validator("code")
    @classmethod
    def normalise_code(cls, value: str) -> str:
        return value.strip().upper()


class TestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None
    created_at: UtcDatetime


class OfferingCreate(BaseModel):
    test_id: int = Field(gt=0)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2, examples=["500.00"])


class OfferingUpdate(BaseModel):
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2, examples=["550.00"])


class OfferingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    test: TestOut
    price: Decimal

    @field_serializer("price")
    def serialize_price(self, value: Decimal) -> str:
        return money(value)


class CentreDetail(CentreOut):
    offerings: list[OfferingOut] = []
