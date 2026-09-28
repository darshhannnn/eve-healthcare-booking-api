"""Payments and the webhook event log used for idempotent processing."""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.db.base import Base


class PaymentStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        # Per-user idempotency (mirrors bookings): the same key from different
        # accounts never collides, so one user's key can't probe another's.
        UniqueConstraint("user_id", "idempotency_key", name="uq_payments_user_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Denormalised owner (booking.user_id at charge time) so idempotency keys
    # can be scoped per user without a join, and ownership checks stay cheap.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    # Reference the "provider" returns and uses in webhook payloads.
    provider_reference: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    # Optional client-supplied key so retried POST /payments calls are safe;
    # paired with a fingerprint of the request so a replayed key with a
    # different payload is rejected instead of silently replayed.
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    booking = relationship("Booking")


class WebhookEventStatus(str, enum.Enum):
    PROCESSED = "PROCESSED"  # event applied (or recognised as a no-op) successfully
    IGNORED = "IGNORED"      # event deliberately not applied (conflicting/cancelled state)
    UNMATCHED = "UNMATCHED"  # references an unknown payment; kept for admin retry


class WebhookEvent(Base):
    """Immutable log of every webhook delivery, keyed by the provider's
    ``event_id``. The unique constraint is what makes processing idempotent
    even under concurrent duplicate deliveries."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    # SET NULL is explicit: an event survives a hard-deleted payment (the
    # payload still documents what was delivered), and UNMATCHED events are
    # null by design.
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
