"""Shared schema primitives: pagination envelope, money formatting, UTC datetimes."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel

from app.core.time import ensure_utc

T = TypeVar("T")


def money(value: Decimal | None) -> str:
    """Format an amount as a fixed 2-decimal string.

    Money travels through the API as strings to avoid floating-point
    representation issues in JavaScript/JSON clients.
    """
    return f"{value:.2f}" if value is not None else "0.00"


def _as_utc(value: datetime) -> datetime:
    """Normalise datetimes to timezone-aware UTC.

    SQLite (local dev/tests) returns naive datetimes; PostgreSQL returns aware
    ones. Normalising at the schema boundary keeps API output consistent.
    Naive input is assumed to be UTC (documented assumption).
    """
    return ensure_utc(value)


#: Use this for every datetime that crosses the API boundary.
UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class Page(BaseModel, Generic[T]):
    """Uniform pagination envelope for all list endpoints."""

    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(cls, items: list[T], total: int, page: int, page_size: int) -> "Page[T]":
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=max(1, (total + page_size - 1) // page_size),
        )
