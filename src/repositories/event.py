from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.delivery import WebhookDelivery
from src.models.event import WebhookEvent, WebhookEventStatus, resolve_event_status


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def create(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        owner_id: str | UUID,
        idempotency_key: str | None = None,
    ) -> WebhookEvent:
        event = WebhookEvent(
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
            owner_id=owner_id,
        )
        self.session.add(event)
        self.session.flush()
        return event

    async def get_by_id(self, *, id: str | UUID, owner_id: str | UUID) -> WebhookEvent | None:
        stmt = select(WebhookEvent).where(
            WebhookEvent.id == id,
            WebhookEvent.owner_id == owner_id,
            WebhookEvent.deleted_at.is_(None),
        )
        return self.session.scalars(stmt).first()

    async def get_by_idempotency_key(
        self,
        *,
        idempotency_key: str,
        owner_id: str | UUID,
    ) -> WebhookEvent | None:
        stmt = select(WebhookEvent).where(
            WebhookEvent.idempotency_key == idempotency_key,
            WebhookEvent.owner_id == owner_id,
            WebhookEvent.deleted_at.is_(None),
        )
        return self.session.scalars(stmt).first()

    async def count(self, *, owner_id: str | UUID, status: WebhookEventStatus | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(WebhookEvent)
            .where(
                WebhookEvent.owner_id == owner_id,
                WebhookEvent.deleted_at.is_(None),
            )
        )
        if status is not None:
            stmt = stmt.where(WebhookEvent.status == status)
        return self.session.scalar(stmt) or 0

    async def list(
        self,
        *,
        owner_id: str | UUID,
        offset: int | None = None,
        limit: int | None = None,
        status: WebhookEventStatus | None = None,
    ) -> list[WebhookEvent]:
        stmt = select(WebhookEvent).where(
            WebhookEvent.owner_id == owner_id,
            WebhookEvent.deleted_at.is_(None),
        )

        if status is not None:
            stmt = stmt.where(WebhookEvent.status == status)

        stmt = stmt.order_by(WebhookEvent.created_at.desc())

        if offset is not None:
            stmt = stmt.offset(offset)

        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.scalars(stmt).all())

    async def update(
        self,
        *,
        event: WebhookEvent,
        data: dict[str, str | int | None],
    ) -> WebhookEvent:
        for key, value in data.items():
            setattr(event, key, value)

        self.session.flush()
        return event

    async def resolve_and_update_status(self, *, event_id: str) -> WebhookEvent | None:
        stmt = (
            select(WebhookEvent)
            .where(
                WebhookEvent.id == event_id,
                WebhookEvent.deleted_at.is_(None),
            )
            .with_for_update()
        )
        event = self.session.scalars(stmt).first()

        if not event:
            return None

        delivery_status_stmt = (
            select(WebhookDelivery.status, func.count())
            .where(WebhookDelivery.event_id == event_id)
            .group_by(WebhookDelivery.status)
        )
        delivery_status_counts = {
            row[0]: row[1] for row in self.session.execute(delivery_status_stmt).all()
        }

        resolved_status = resolve_event_status(delivery_status_counts)

        if event.status != resolved_status:
            event.status = resolved_status
            self.session.flush()

        return event
