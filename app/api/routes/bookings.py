"""Booking endpoints. All require authentication; users only see and manage
their own bookings, admins can access any booking."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_pagination
from app.models.booking import BookingStatus
from app.models.user import User
from app.schemas.booking import BookingCreate, BookingOut
from app.schemas.common import Page
from app.services import booking_service
from app.db.session import get_db
from app.utils.rate_limit import rate_limit

router = APIRouter()

_MUTATION_LIMIT = "RATE_LIMIT_MUTATIONS_PER_MINUTE"


@router.post(
    "/bookings",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Book a diagnostic test at a centre (auth)",
    dependencies=[Depends(rate_limit("mutations", _MUTATION_LIMIT))],
)
def create_booking(
    payload: BookingCreate,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            max_length=120,
            description="Send the same key to safely retry this call; the "
            "original booking is returned instead of creating a duplicate.",
        ),
    ] = None,
) -> BookingOut:
    booking, replayed = booking_service.create_booking(
        db, user.id, payload, idempotency_key or None
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
    return BookingOut.model_validate(booking)


@router.get(
    "/bookings",
    response_model=Page[BookingOut],
    summary="List bookings (own bookings; admins see all)",
)
def list_bookings(
    status_filter: BookingStatus | None = Query(default=None, alias="status"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pagination: tuple[int, int] = Depends(get_pagination),
) -> Page[BookingOut]:
    page, page_size = pagination
    items, total = booking_service.list_bookings(db, user, status_filter, page, page_size)
    return Page[BookingOut].build(
        [BookingOut.model_validate(b) for b in items], total, page, page_size
    )


@router.get(
    "/bookings/{booking_id}",
    response_model=BookingOut,
    summary="Booking detail (owner or admin)",
)
def get_booking(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BookingOut:
    booking = booking_service.get_booking_for_user(db, booking_id, user)
    return BookingOut.model_validate(booking)


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=BookingOut,
    summary="Cancel a booking (owner or admin; future appointments only)",
    dependencies=[Depends(rate_limit("mutations", _MUTATION_LIMIT))],
)
def cancel_booking(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BookingOut:
    booking = booking_service.get_booking_for_user(db, booking_id, user)
    booking = booking_service.cancel_booking(db, booking)
    return BookingOut.model_validate(booking)
