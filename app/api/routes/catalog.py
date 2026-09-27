"""Diagnostic centres, their test offerings, and the global test catalogue.

Reads are public (patients browse centres/tests); writes require ADMIN.
Admin mutations invalidate the read cache.
"""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_pagination, require_admin
from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.db.session import get_db
from app.models.catalog import CentreOffering, DiagnosticCentre, DiagnosticTest
from app.models.user import User
from app.schemas.catalog import (
    CentreCreate,
    CentreDetail,
    CentreOut,
    CentreUpdate,
    OfferingCreate,
    OfferingOut,
    OfferingUpdate,
    TestCreate,
    TestOut,
)
from app.schemas.common import Page
from app.utils.cache import cache_clear, cache_get, cache_set

router = APIRouter()


@router.get(
    "/centres",
    response_model=Page[CentreOut],
    summary="List diagnostic centres (public, paginated, searchable)",
)
def list_centres(
    db: Session = Depends(get_db),
    pagination: tuple[int, int] = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100, description="Match name or location"),
) -> Page[CentreOut]:
    page, page_size = pagination
    cache_key = f"centres:list:{page}:{page_size}:{search or ''}"
    cached = cache_get(cache_key)
    if cached is not None:
        return Page[CentreOut](**cached)

    stmt = select(DiagnosticCentre)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                DiagnosticCentre.name.ilike(pattern),
                DiagnosticCentre.location.ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    centres = db.scalars(
        stmt.order_by(DiagnosticCentre.id).offset((page - 1) * page_size).limit(page_size)
    ).all()

    result = Page[CentreOut].build(
        [CentreOut.model_validate(c) for c in centres], int(total), page, page_size
    )
    cache_set(cache_key, result.model_dump(mode="json"), get_settings().CACHE_CENTRES_TTL_SECONDS)
    return result


@router.get(
    "/centres/{centre_id}",
    response_model=CentreDetail,
    summary="Centre detail including available tests and prices (public)",
)
def get_centre(centre_id: int, db: Session = Depends(get_db)) -> CentreDetail:
    cache_key = f"centres:detail:{centre_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return CentreDetail(**cached)

    centre = db.scalars(
        select(DiagnosticCentre)
        .where(DiagnosticCentre.id == centre_id)
        .options(selectinload(DiagnosticCentre.offerings).selectinload(CentreOffering.test))
    ).first()
    if centre is None or not centre.is_active:
        raise NotFoundError("Diagnostic centre not found")

    result = CentreDetail.model_validate(centre)
    cache_set(cache_key, result.model_dump(mode="json"), get_settings().CACHE_CENTRES_TTL_SECONDS)
    return result


@router.post(
    "/centres",
    response_model=CentreOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a diagnostic centre (admin)",
    dependencies=[Depends(require_admin)],
)
def create_centre(payload: CentreCreate, db: Session = Depends(get_db)) -> DiagnosticCentre:
    centre = DiagnosticCentre(name=payload.name.strip(), location=payload.location.strip())
    db.add(centre)
    db.commit()
    db.refresh(centre)
    cache_clear()
    return centre


@router.patch(
    "/centres/{centre_id}",
    response_model=CentreOut,
    summary="Update a centre's name/location (admin)",
    dependencies=[Depends(require_admin)],
)
def update_centre(
    centre_id: int, payload: CentreUpdate, db: Session = Depends(get_db)
) -> DiagnosticCentre:
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None:
        raise NotFoundError("Diagnostic centre not found")
    if payload.name is not None:
        centre.name = payload.name.strip()
    if payload.location is not None:
        centre.location = payload.location.strip()
    db.commit()
    db.refresh(centre)
    cache_clear()
    return centre


@router.post(
    "/centres/{centre_id}/offerings",
    response_model=OfferingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Offer a test at a centre with a price (admin)",
    dependencies=[Depends(require_admin)],
)
def add_offering(
    centre_id: int, payload: OfferingCreate, db: Session = Depends(get_db)
) -> CentreOffering:
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None:
        raise NotFoundError("Diagnostic centre not found")
    test = db.get(DiagnosticTest, payload.test_id)
    if test is None:
        raise NotFoundError("Diagnostic test not found")

    existing = db.scalar(
        select(CentreOffering).where(
            CentreOffering.centre_id == centre_id, CentreOffering.test_id == test.id
        )
    )
    if existing is not None:
        raise ConflictError("This test is already offered at this centre")

    offering = CentreOffering(centre_id=centre_id, test_id=test.id, price=payload.price)
    db.add(offering)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("This test is already offered at this centre")
    db.refresh(offering)
    cache_clear()
    return offering


@router.patch(
    "/centres/{centre_id}/offerings/{test_id}",
    response_model=OfferingOut,
    summary="Update the price of a test at a centre (admin)",
    dependencies=[Depends(require_admin)],
)
def update_offering(
    centre_id: int, test_id: int, payload: OfferingUpdate, db: Session = Depends(get_db)
) -> CentreOffering:
    offering = db.scalar(
        select(CentreOffering).where(
            CentreOffering.centre_id == centre_id, CentreOffering.test_id == test_id
        )
    )
    if offering is None:
        raise NotFoundError("This test is not offered at this centre")
    offering.price = payload.price
    db.commit()
    db.refresh(offering)
    cache_clear()
    return offering


@router.delete(
    "/centres/{centre_id}/offerings/{test_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop offering a test at a centre (admin)",
    dependencies=[Depends(require_admin)],
)
def remove_offering(centre_id: int, test_id: int, db: Session = Depends(get_db)) -> Response:
    offering = db.scalar(
        select(CentreOffering).where(
            CentreOffering.centre_id == centre_id, CentreOffering.test_id == test_id
        )
    )
    if offering is None:
        raise NotFoundError("This test is not offered at this centre")
    db.delete(offering)
    db.commit()
    cache_clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/tests",
    response_model=Page[TestOut],
    summary="List the diagnostic test catalogue (public, paginated, searchable)",
)
def list_tests(
    db: Session = Depends(get_db),
    pagination: tuple[int, int] = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100, description="Match code or name"),
) -> Page[TestOut]:
    page, page_size = pagination
    cache_key = f"tests:list:{page}:{page_size}:{search or ''}"
    cached = cache_get(cache_key)
    if cached is not None:
        return Page[TestOut](**cached)

    stmt = select(DiagnosticTest)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(DiagnosticTest.code.ilike(pattern), DiagnosticTest.name.ilike(pattern))
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    tests = db.scalars(
        stmt.order_by(DiagnosticTest.id).offset((page - 1) * page_size).limit(page_size)
    ).all()

    result = Page[TestOut].build(
        [TestOut.model_validate(t) for t in tests], int(total), page, page_size
    )
    cache_set(cache_key, result.model_dump(mode="json"), get_settings().CACHE_CENTRES_TTL_SECONDS)
    return result


@router.post(
    "/tests",
    response_model=TestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a test to the catalogue (admin)",
    dependencies=[Depends(require_admin)],
)
def create_test(payload: TestCreate, db: Session = Depends(get_db)) -> DiagnosticTest:
    existing = db.scalar(
        select(func.count()).select_from(DiagnosticTest).where(DiagnosticTest.code == payload.code)
    )
    if existing:
        raise ConflictError(f"A test with code '{payload.code}' already exists")

    test = DiagnosticTest(
        code=payload.code, name=payload.name.strip(), description=payload.description
    )
    db.add(test)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError(f"A test with code '{payload.code}' already exists")
    db.refresh(test)
    cache_clear()
    return test
