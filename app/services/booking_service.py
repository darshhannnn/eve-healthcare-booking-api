"""Booking use-cases: creation, listing/ownership, cancellation."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.time import ensure_utc, utcnow
from app.models.booking import Booking, BookingStatus
from app.models.catalog import CentreOffering, DiagnosticCentre, DiagnosticTest
from app.models.user import User, UserRole
from app.schemas.booking import BookingCreate

_ACTIVE_STATUSES = (BookingStatus.PENDING.value, BookingStatus.CONFIRMED.value)


def create_booking(db: Session, user_id: int, payload: BookingCreate) -> Booking:
    centre = db.get(DiagnosticCentre, payload.centre_id)
    if centre is None or not centre.is_active:
        raise NotFoundError("Diagnostic centre not found")

    test = db.get(DiagnosticTest, payload.test_id)
    if test is None:
        raise NotFoundError("Diagnostic test not found")

    offering = db.execute(
        select(CentreOffering).where(
            CentreOffering.centre_id == centre.id,
            CentreOffering.test_id == test.id,
        )
    ).scalar_one_or_none()
    if offering is None:
        raise UnprocessableError(f"Test '{test.name}' is not offered at centre '{centre.name}'")

    appointment_at = ensure_utc(payload.appointment_at)
    if appointment_at <= utcnow():
        raise UnprocessableError("Appointment date/time must be in the future")

    duplicate = db.scalar(
        select(func.count()).select_from(Booking).where(
            Booking.user_id == user_id,
            Booking.centre_id == centre.id,
            Booking.test_id == test.id,
            Booking.appointment_at == appointment_at,
            Booking.status != BookingStatus.CANCELLED.value,
        )
    )
    if duplicate:
        raise ConflictError(
            "You already have an active booking for this test at the selected time"
        )

    booking = Booking(
        user_id=user_id,
        centre_id=centre.id,
        test_id=test.id,
        appointment_at=appointment_at,
        amount=offering.price,  # snapshot — later price changes don't touch existing bookings
        status=BookingStatus.PENDING.value,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def get_booking_for_user(db: Session, booking_id: int, user: User) -> Booking:
    """Load a booking enforcing that it is either owned by ``user`` or that
    ``user`` is an admin. 403 (not 404) so unauthorised access attempts are
    explicit and testable."""
    booking = db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(selectinload(Booking.centre), selectinload(Booking.test))
    ).scalar_one_or_none()
    if booking is None:
        raise NotFoundError("Booking not found")
    if booking.user_id != user.id and user.role != UserRole.ADMIN.value:
        raise ForbiddenError("You do not have access to this booking")
    return booking


def list_bookings(
    db: Session,
    user: User,
    status: BookingStatus | None,
    page: int,
    page_size: int,
) -> tuple[list[Booking], int]:
    filters = []
    if user.role != UserRole.ADMIN.value:
        filters.append(Booking.user_id == user.id)
    if status is not None:
        filters.append(Booking.status == status.value)

    total = db.scalar(select(func.count()).select_from(Booking).where(*filters)) or 0
    items = db.execute(
        select(Booking)
        .where(*filters)
        .options(selectinload(Booking.centre), selectinload(Booking.test))
        .order_by(Booking.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return list(items), int(total)


def cancel_booking(db: Session, booking: Booking) -> Booking:
    """Cancel rules: only PENDING/CONFIRMED bookings with a future
    appointment can be cancelled; FAILED/CANCELLED are terminal."""
    if booking.status not in _ACTIVE_STATUSES:
        raise ConflictError(f"A {booking.status} booking cannot be cancelled")
    if ensure_utc(booking.appointment_at) <= utcnow():
        raise ConflictError("Bookings whose appointment time has passed cannot be cancelled")

    booking.status = BookingStatus.CANCELLED.value
    db.commit()
    db.refresh(booking)
    return booking
