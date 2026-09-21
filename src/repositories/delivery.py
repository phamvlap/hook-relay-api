from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from src.models.delivery import WebhookDelivery, WebhookDeliveryStatus


class DeliveryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def create(
        self,
        *,
        event_id: str | UUID,
        endpoint_id: str | UUID,
        owner_id: str | UUID,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(event_id=event_id, endpoint_id=endpoint_id, owner_id=owner_id)
        self.session.flush()
        return delivery

    async def bulk_create(self, *, deliveries: list[WebhookDelivery]) -> None:
        self.session.add_all(deliveries)
        self.session.flush()

    async def get_by_id(self, *, id: str | UUID, owner_id: str | UUID) -> WebhookDelivery | None:
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.id == id,
                WebhookDelivery.owner_id == owner_id,
                WebhookDelivery.deleted_at.is_(None),
            )
            .options(joinedload(WebhookDelivery.endpoint), joinedload(WebhookDelivery.event))
        )
        return self.session.scalars(stmt).first()

    async def count(
        self,
        *,
        owner_id: str | UUID,
        event_id: str | UUID | None = None,
        endpoint_id: str | UUID | None = None,
        status: WebhookDeliveryStatus | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(WebhookDelivery)
            .where(
                WebhookDelivery.owner_id == owner_id,
                WebhookDelivery.deleted_at.is_(None),
            )
        )

        if event_id is not None:
            stmt = stmt.where(WebhookDelivery.event_id == event_id)

        if endpoint_id is not None:
            stmt = stmt.where(WebhookDelivery.endpoint_id == endpoint_id)

        if status is not None:
            stmt = stmt.where(WebhookDelivery.status == status)

        return self.session.scalar(stmt) or 0

    async def list(
        self,
        *,
        owner_id: str | UUID,
        offset: int | None = None,
        limit: int | None = None,
        event_id: str | UUID | None = None,
        endpoint_id: str | UUID | None = None,
        status: WebhookDeliveryStatus | None = None,
    ) -> list[WebhookDelivery]:
        stmt = select(WebhookDelivery).where(
            WebhookDelivery.owner_id == owner_id,
            WebhookDelivery.deleted_at.is_(None),
        )

        if event_id is not None:
            stmt = stmt.where(WebhookDelivery.event_id == event_id).options(
                joinedload(WebhookDelivery.event)
            )

        if endpoint_id is not None:
            stmt = stmt.where(WebhookDelivery.endpoint_id == endpoint_id).options(
                joinedload(WebhookDelivery.endpoint)
            )

        if status is not None:
            stmt = stmt.where(WebhookDelivery.status == status)

        stmt = stmt.order_by(WebhookDelivery.created_at.desc())

        if offset is not None:
            stmt = stmt.offset(offset)

        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.scalars(stmt).all())

    async def update(
        self,
        *,
        delivery: WebhookDelivery,
        data: dict[str, str | int | None],
    ) -> WebhookDelivery:
        for key, value in data.items():
            setattr(delivery, key, value)

        self.session.flush()
        return delivery

    async def mark_as_delivering(self, *, delivery: WebhookDelivery) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.DELIVERING

        self.session.flush()

        return delivery

    async def mark_as_success(
        self,
        *,
        delivery: WebhookDelivery,
        status_code: int,
        response_body: dict[str, Any] | None,
        duration_ms: int,
    ) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.SUCCESS
        delivery.status_code = status_code
        delivery.duration_ms = duration_ms
        delivery.delivered_at = datetime.now(tz=UTC)

        if response_body is not None:
            delivery.response_body = response_body

        self.session.flush()

        return delivery

    async def mark_as_failed(
        self,
        *,
        delivery: WebhookDelivery,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.FAILED
        delivery.status_code = status_code
        delivery.error_message = error_message
        delivery.duration_ms = duration_ms
        delivery.next_retry_at = None

        if response_body is not None:
            delivery.response_body = response_body

        self.session.flush()

        return delivery

    async def mark_as_dead_letter(
        self,
        *,
        delivery: WebhookDelivery,
        attempt: int,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.DEAD_LETTER
        delivery.attempt = attempt
        delivery.status_code = status_code
        delivery.error_message = error_message
        delivery.duration_ms = duration_ms

        if response_body is not None:
            delivery.response_body = response_body

        self.session.flush()

        return delivery

    async def mark_as_retrying(
        self,
        *,
        delivery: WebhookDelivery,
        next_retry_at: datetime,
        attempt: int,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.RETRYING
        delivery.next_retry_at = next_retry_at
        delivery.attempt = attempt
        delivery.status_code = status_code
        delivery.error_message = error_message
        delivery.duration_ms = duration_ms

        if response_body is not None:
            delivery.response_body = response_body

        self.session.flush()

        return delivery

    async def get_delivery_for_processing(
        self,
        *,
        delivery_id: str | UUID,
    ) -> WebhookDelivery | None:
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.id == delivery_id,
                WebhookDelivery.deleted_at.is_(None),
                WebhookDelivery.status.in_(
                    [
                        WebhookDeliveryStatus.QUEUED,
                        WebhookDeliveryStatus.RETRYING,
                    ]
                ),
            )
            .options(
                joinedload(WebhookDelivery.endpoint),
                joinedload(WebhookDelivery.event),
            )
            .with_for_update()
        )
        return self.session.scalars(stmt).first()
