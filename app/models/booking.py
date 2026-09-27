import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    centre = relationship("DiagnosticCentre")
    test = relationship("DiagnosticTest")
