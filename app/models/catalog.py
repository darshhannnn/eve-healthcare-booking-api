"""Diagnostic centre / test catalog.

A centre does not duplicate test definitions. ``DiagnosticTest`` is the global
catalogue and ``CentreOffering`` links a centre to a test *with that centre's
price*, so the same test can cost differently per centre and price changes
never affect already-created bookings (bookings snapshot the amount).
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.db.base import Base


class DiagnosticTest(Base):
    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class DiagnosticCentre(Base):
    __tablename__ = "diagnostic_centres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    offerings: Mapped[list["CentreOffering"]] = relationship(
        back_populates="centre", cascade="all, delete-orphan"
    )


class CentreOffering(Base):
    __tablename__ = "centre_offerings"
    __table_args__ = (UniqueConstraint("centre_id", "test_id", name="uq_centre_offering"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_centres.id", ondelete="CASCADE"), index=True, nullable=False
    )
    test_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_tests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    centre: Mapped["DiagnosticCentre"] = relationship(back_populates="offerings")
    test: Mapped["DiagnosticTest"] = relationship()
