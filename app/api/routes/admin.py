"""Admin/ops endpoints: inspect and retry webhook events."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_pagination, require_admin
from app.db.session import get_db
from app.models.payment import WebhookEvent, WebhookEventStatus
from app.schemas.common import Page
from app.schemas.payment import WebhookAck, WebhookEventOut
from app.services import payment_service

router = APIRouter()


@router.get(
    "/admin/webhook-events",
    response_model=Page[WebhookEventOut],
    summary="Inspect webhook deliveries (admin)",
)
def list_webhook_events(
    status_filter: WebhookEventStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    pagination: tuple[int, int] = Depends(get_pagination),
    _admin: object = Depends(require_admin),
) -> Page[WebhookEventOut]:
    page, page_size = pagination
    filters = []
    if status_filter is not None:
        filters.append(WebhookEvent.status == status_filter.value)

    total = db.scalar(select(func.count()).select_from(WebhookEvent).where(*filters)) or 0
    events = db.scalars(
        select(WebhookEvent)
        .where(*filters)
        .order_by(WebhookEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[WebhookEventOut].build(
        [WebhookEventOut.model_validate(e) for e in events], int(total), page, page_size
    )


@router.post(
    "/admin/webhook-events/{event_row_id}/retry",
    response_model=WebhookAck,
    summary="Reprocess a stored webhook event (admin)",
)
def retry_webhook_event(
    event_row_id: int,
    db: Session = Depends(get_db),
    _admin: object = Depends(require_admin),
) -> WebhookAck:
    result = payment_service.retry_webhook_event(db, event_row_id)
    return WebhookAck(received=True, event_id=result["event_id"], result=result["result"], detail=result.get("detail"))
