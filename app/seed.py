"""Idempotent database seeding.

* ``seed_admin`` — bootstrap the admin account from settings (runs on startup).
* ``seed_demo_data`` — a small demo dataset (centres, tests, offerings, a demo
  user) for trying the API quickly. Enabled via ``SEED_DEMO_DATA=true``
  (docker-compose sets it) or ``python -m app.seed``.
"""

import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.catalog import CentreOffering, DiagnosticCentre, DiagnosticTest
from app.models.user import User, UserRole

logger = logging.getLogger("eve.seed")


def seed_admin(db: Session) -> None:
    settings = get_settings()
    existing = db.scalar(select(User).where(User.email == settings.ADMIN_EMAIL))
    if existing is not None:
        return
    db.add(
        User(
            email=settings.ADMIN_EMAIL,
            full_name=settings.ADMIN_FULL_NAME,
            hashed_password=hash_password(settings.ADMIN_PASSWORD),
            role=UserRole.ADMIN.value,
        )
    )
    db.commit()
    logger.info("seeded admin user", extra={"email": settings.ADMIN_EMAIL})


def seed_demo_data(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(DiagnosticCentre)):
        return  # already seeded

    tests = {
        "CBC": ("Complete Blood Count", "Screens for anaemia, infection and blood disorders."),
        "LFT": ("Liver Function Test", "Enzymes and bilirubin to assess liver health."),
        "KFT": ("Kidney Function Test", "Creatinine, urea and electrolytes."),
        "LIPID": ("Lipid Profile", "Cholesterol, triglycerides and lipoproteins."),
        "THYROID": ("Thyroid Profile", "T3, T4 and TSH levels."),
        "HBA1C": ("HbA1c", "Three-month average blood sugar."),
        "VITD": ("Vitamin D (25-OH)", "Vitamin D deficiency screening."),
    }
    test_rows: dict[str, DiagnosticTest] = {}
    for code, (name, description) in tests.items():
        row = DiagnosticTest(code=code, name=name, description=description)
        db.add(row)
        test_rows[code] = row

    centres = [
        ("EVE Diagnostics — Indiranagar", "12, 100ft Road, Indiranagar, Bengaluru"),
        ("EVE Diagnostics — Andheri West", "3, Link Road, Andheri West, Mumbai"),
        ("EVE Wellness Labs — Hitech City", "Cyber Towers Road, Hitech City, Hyderabad"),
    ]
    centre_rows = []
    for name, location in centres:
        row = DiagnosticCentre(name=name, location=location)
        db.add(row)
        centre_rows.append(row)

    db.flush()  # assign IDs so offerings can reference them

    # (centre index, test code, price)
    offerings = [
        (0, "CBC", "299.00"), (0, "LFT", "599.00"), (0, "LIPID", "499.00"),
        (0, "THYROID", "549.00"), (0, "VITD", "1099.00"),
        (1, "CBC", "349.00"), (1, "KFT", "649.00"), (1, "HBA1C", "399.00"),
        (1, "LIPID", "549.00"),
        (2, "CBC", "279.00"), (2, "THYROID", "599.00"), (2, "HBA1C", "449.00"),
        (2, "VITD", "999.00"), (2, "LFT", "549.00"),
    ]
    for centre_idx, code, price in offerings:
        db.add(
            CentreOffering(
                centre_id=centre_rows[centre_idx].id,
                test_id=test_rows[code].id,
                price=Decimal(price),
            )
        )

    settings = get_settings()
    if db.scalar(select(User).where(User.email == settings.DEMO_USER_EMAIL)) is None:
        db.add(
            User(
                email=settings.DEMO_USER_EMAIL,
                full_name="Demo Patient",
                hashed_password=hash_password(settings.DEMO_USER_PASSWORD),
                role=UserRole.USER.value,
            )
        )

    db.commit()
    logger.info("seeded demo data", extra={"centres": len(centre_rows), "tests": len(test_rows)})


def main() -> None:
    from app.db.base import Base
    from app.db.session import get_engine

    Base.metadata.create_all(bind=get_engine())
    with Session(bind=get_engine(), expire_on_commit=False) as db:
        seed_admin(db)
        seed_demo_data(db)


if __name__ == "__main__":
    main()
