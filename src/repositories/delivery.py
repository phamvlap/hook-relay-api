from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, selectinload

from src.core.config import settings
from src.database.session import get_local_session
from src.models.delivery import WebhookDelivery, WebhookDeliveryStatus


class DeliveryRepository:
    def __init__(self, session: Session | None = None):
        if session is None:
            session = get_local_session(str(settings.postgres_dsn))
        self.session = session

    async def create(
        self,
        *,
        event_id: str,
        endpoint_id: str,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(event_id=event_id, endpoint_id=endpoint_id)
        self.session.add(delivery)
        self.session.commit()
        self.session.refresh(delivery)
        return delivery

    async def bulk_create(self, *, data: list[dict[str, str]]) -> list[WebhookDelivery]:
        deliveries: list[WebhookDelivery] = []
        for item in data:
            delivery = WebhookDelivery(**item)
            deliveries.append(delivery)

        self.session.add_all(deliveries)
        self.session.commit()

        for delivery in deliveries:
            self.session.refresh(delivery)

        return deliveries

    async def get_by_id(self, *, id: str) -> WebhookDelivery | None:
        return (
            self.session.query(WebhookDelivery)
            .filter_by(id=id, deleted_at=None)
            .options(selectinload(WebhookDelivery.endpoint), selectinload(WebhookDelivery.event))
            .first()
        )

    async def count(
        self,
        event_id: str | None = None,
        endpoint_id: str | None = None,
        status: WebhookDeliveryStatus | None = None,
    ) -> int:
        query = self.session.query(WebhookDelivery).filter_by(deleted_at=None)

        if event_id is not None:
            query = query.filter_by(event_id=event_id)

        if endpoint_id is not None:
            query = query.filter_by(endpoint_id=endpoint_id)

        if status is not None:
            query = query.filter_by(status=status)

        return query.count()

    async def list(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
        event_id: str | None = None,
        endpoint_id: str | None = None,
        status: WebhookDeliveryStatus | None = None,
    ) -> list[WebhookDelivery]:
        query = self.session.query(WebhookDelivery).filter_by(deleted_at=None)

        if event_id is not None:
            query = query.filter_by(event_id=event_id).options(selectinload(WebhookDelivery.event))

        if endpoint_id is not None:
            query = query.filter_by(endpoint_id=endpoint_id).options(
                selectinload(WebhookDelivery.endpoint)
            )

        if status is not None:
            query = query.filter_by(status=status)

        query = query.order_by(WebhookDelivery.created_at.desc())

        if offset is not None:
            query = query.offset(offset)

        if limit is not None:
            query = query.limit(limit)

        return query.all()

    async def update(
        self,
        *,
        delivery: WebhookDelivery,
        data: dict[str, str | int | None],
    ) -> WebhookDelivery:
        for key, value in data.items():
            setattr(delivery, key, value)

        self.session.flush()
        self.session.commit()
        self.session.refresh(delivery)
        return delivery

    async def mark_as_delivering(self, *, delivery: WebhookDelivery) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.DELIVERING

        self.session.flush()
        self.session.commit()
        self.session.refresh(delivery)

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
        self.session.commit()
        self.session.refresh(delivery)

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
        self.session.commit()
        self.session.refresh(delivery)

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
        self.session.commit()
        self.session.refresh(delivery)

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
        self.session.commit()
        self.session.refresh(delivery)

        return delivery
