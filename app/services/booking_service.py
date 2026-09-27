"""Booking use-cases: creation, listing/ownership, cancellation."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.time import ensure_utc, utcnow
from app.models.booking import Booking, BookingStatus
from app.models.catalog import CentreOffering, DiagnosticCentre, DiagnosticTest
from app.models.user import User, UserRole
from app.schemas.booking import BookingCreate

_ACTIVE_STATUSES = (BookingStatus.PENDING.value, BookingStatus.CONFIRMED.value)


def create_booking(
    db: Session, user_id: int, payload: BookingCreate, idempotency_key: str | None = None
) -> tuple[Booking, bool]:
    """Create a booking. Returns ``(booking, replayed)`` — ``replayed`` is True
    when an ``Idempotency-Key`` previously seen by this user is satisfied from
    the store instead of booking again.

    Concurrency: the duplicate-slot check below is a read-then-insert, which
    is racy on its own, so the user's row is locked ``FOR UPDATE`` first to
    serialize the same user's booking creations (PostgreSQL; a no-op on the
    SQLite used for dev/tests, which is single-threaded). The
    ``IntegrityError`` fallback is the last line of defence.
    """
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise NotFoundError("User not found")

    if idempotency_key:
        existing = db.scalar(
            select(Booking).where(
                Booking.user_id == user_id,
                Booking.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing, True

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
        idempotency_key=idempotency_key,
    )
    db.add(booking)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race: the same slot (or the same idempotency key) was
        # created concurrently — the winner is already committed.
        db.rollback()
        if idempotency_key:
            replay = db.scalar(
                select(Booking).where(Booking.idempotency_key == idempotency_key)
            )
            if replay is not None and replay.user_id == user_id:
                return replay, True
            raise ConflictError("This Idempotency-Key was already used with another account")
        raise ConflictError(
            "You already have an active booking for this test at the selected time"
        )
    db.refresh(booking)
    return booking, False


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
