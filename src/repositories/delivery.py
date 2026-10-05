from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.models.delivery import (
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookDeliveryStatus,
)


class DeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        event_id: str | UUID,
        endpoint_id: str | UUID,
        owner_id: str | UUID,
        secret_version: int = 1,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(
            event_id=event_id,
            endpoint_id=endpoint_id,
            owner_id=owner_id,
            secret_version=secret_version,
        )
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def bulk_create(self, *, deliveries: list[WebhookDelivery]) -> None:
        self.session.add_all(deliveries)
        await self.session.flush()

    async def get_by_id(self, *, id: str | UUID, owner_id: str | UUID) -> WebhookDelivery | None:
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.id == id,
                WebhookDelivery.owner_id == owner_id,
                WebhookDelivery.deleted_at.is_(None),
            )
            .options(
                joinedload(WebhookDelivery.endpoint),
                joinedload(WebhookDelivery.event),
                selectinload(WebhookDelivery.attempts),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

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

        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def find_many(
        self,
        *,
        owner_id: str | UUID,
        offset: int | None = None,
        limit: int | None = None,
        event_id: str | UUID | None = None,
        endpoint_id: str | UUID | None = None,
        status: WebhookDeliveryStatus | None = None,
    ) -> list[WebhookDelivery]:
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.owner_id == owner_id,
                WebhookDelivery.deleted_at.is_(None),
            )
            .options(
                joinedload(WebhookDelivery.endpoint),
                joinedload(WebhookDelivery.event),
            )
        )

        if event_id is not None:
            stmt = stmt.where(WebhookDelivery.event_id == event_id)

        if endpoint_id is not None:
            stmt = stmt.where(WebhookDelivery.endpoint_id == endpoint_id)

        if status is not None:
            stmt = stmt.where(WebhookDelivery.status == status)

        stmt = stmt.order_by(WebhookDelivery.created_at.desc())

        if offset is not None:
            stmt = stmt.offset(offset)

        if limit is not None:
            stmt = stmt.limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        *,
        delivery: WebhookDelivery,
        data: dict[str, str | int | None],
    ) -> WebhookDelivery:
        for key, value in data.items():
            setattr(delivery, key, value)

        await self.session.flush()
        return delivery

    async def mark_as_delivering(self, *, delivery: WebhookDelivery) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.DELIVERING

        await self.session.flush()

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

        await self.session.flush()

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

        await self.session.flush()

        return delivery

    async def mark_as_dead_letter(
        self,
        *,
        delivery: WebhookDelivery,
        attempt: int,
        retry_count: int | None = None,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.DEAD_LETTER
        delivery.attempt = attempt
        if retry_count is not None:
            delivery.retry_count = retry_count
        delivery.status_code = status_code
        delivery.error_message = error_message
        delivery.duration_ms = duration_ms

        if response_body is not None:
            delivery.response_body = response_body

        await self.session.flush()

        return delivery

    async def mark_as_retrying(
        self,
        *,
        delivery: WebhookDelivery,
        next_retry_at: datetime,
        attempt: int,
        retry_count: int | None = None,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.RETRYING
        delivery.next_retry_at = next_retry_at
        delivery.attempt = attempt
        if retry_count is not None:
            delivery.retry_count = retry_count
        delivery.status_code = status_code
        delivery.error_message = error_message
        delivery.duration_ms = duration_ms

        if response_body is not None:
            delivery.response_body = response_body

        await self.session.flush()

        return delivery

    async def get_by_id_for_update(
        self,
        *,
        delivery_id: str | UUID,
        owner_id: str | UUID,
    ) -> WebhookDelivery | None:
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.id == delivery_id,
                WebhookDelivery.owner_id == owner_id,
                WebhookDelivery.deleted_at.is_(None),
            )
            .options(
                selectinload(WebhookDelivery.endpoint),
                selectinload(WebhookDelivery.event),
                selectinload(WebhookDelivery.attempts),
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def mark_as_queued_for_retry(self, *, delivery: WebhookDelivery) -> WebhookDelivery:
        delivery.status = WebhookDeliveryStatus.QUEUED
        delivery.retry_count = 0
        delivery.manual_retry_count += 1
        delivery.next_retry_at = None
        delivery.status_code = None
        delivery.response_body = None
        delivery.error_message = None
        delivery.duration_ms = None
        delivery.delivered_at = None

        await self.session.flush()

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
                selectinload(WebhookDelivery.endpoint),
                selectinload(WebhookDelivery.event),
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_stuck_deliveries_for_update(
        self,
        *,
        stuck_before: datetime,
        limit: int = 100,
    ) -> list[WebhookDelivery]:
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == WebhookDeliveryStatus.DELIVERING,
                WebhookDelivery.updated_at <= stuck_before,
                WebhookDelivery.deleted_at.is_(None),
            )
            .options(
                selectinload(WebhookDelivery.endpoint),
                selectinload(WebhookDelivery.event),
            )
            .order_by(WebhookDelivery.updated_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class DeliveryAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        delivery_id: str | UUID,
        attempt_number: int,
        started_at: datetime,
        completed_at: datetime,
        duration_ms: int | None = None,
        status_code: int | None = None,
        request_headers: dict[str, Any] | None = None,
        response_headers: dict[str, Any] | None = None,
        response_body: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> WebhookDeliveryAttempt:
        attempt = WebhookDeliveryAttempt(
            delivery_id=delivery_id,
            attempt_number=attempt_number,
            status_code=status_code,
            request_headers=request_headers,
            response_headers=response_headers,
            response_body=response_body,
            error_message=error_message,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=completed_at,
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def count_by_delivery_id(self, *, delivery_id: str | UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(WebhookDeliveryAttempt)
            .where(
                WebhookDeliveryAttempt.delivery_id == delivery_id,
                WebhookDeliveryAttempt.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def list_by_delivery_id(
        self,
        *,
        delivery_id: str | UUID,
        offset: int | None = None,
        limit: int | None = None,
    ) -> list[WebhookDeliveryAttempt]:
        stmt = select(WebhookDeliveryAttempt).where(
            WebhookDeliveryAttempt.delivery_id == delivery_id,
            WebhookDeliveryAttempt.deleted_at.is_(None),
        )

        if offset is not None:
            stmt = stmt.offset(offset)

        if limit is not None:
            stmt = stmt.limit(limit)

        stmt = stmt.order_by(WebhookDeliveryAttempt.attempt_number.asc())

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
