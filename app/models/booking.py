import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.db.base import Base


class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"      # created, awaiting payment
    CONFIRMED = "CONFIRMED"  # payment succeeded
    FAILED = "FAILED"        # payment failed
    CANCELLED = "CANCELLED"  # cancelled by the user/admin before or after payment


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_user_status", "user_id", "status"),
        # Per-user idempotency: the same key from different accounts never
        # collides, so one user's key can't probe another's.
        UniqueConstraint("user_id", "idempotency_key", name="uq_bookings_user_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    centre_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_centres.id"), index=True, nullable=False
    )
    test_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_tests.id"), index=True, nullable=False
    )
    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Amount is snapshotted from the centre offering at booking time.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=BookingStatus.PENDING.value, index=True, nullable=False
    )
    # Optional client-supplied key so retried POST /bookings calls are safe
    # (mirrors payments). Unique per user, and paired with a fingerprint of
    # the request so a replayed key with a different payload is rejected.
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    centre = relationship("DiagnosticCentre")
    test = relationship("DiagnosticTest")


# DB-level defence in depth for the duplicate-slot rule: a user cannot have two
# non-cancelled bookings for the same centre+test+slot. The .ddl_if() guard
# means create_all (and Alembic) only emits this index on PostgreSQL; on SQLite
# (dev/tests) it is silently skipped, leaving re-booking after cancellation
# unblocked (the app-level check runs first and is the primary guard there).
_active_slot_index = Index(
    "uq_bookings_active_slot",
    Booking.user_id,
    Booking.centre_id,
    Booking.test_id,
    Booking.appointment_at,
    unique=True,
    postgresql_where=text("status != 'CANCELLED'"),
).ddl_if(dialect="postgresql")
