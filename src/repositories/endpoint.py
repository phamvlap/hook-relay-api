from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.endpoint import WebhookEndpoint, WebhookEndpointStatus


class EndpointRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def create(
        self,
        *,
        name: str,
        url: str,
        max_retries: int,
        owner_id: str | UUID,
    ) -> WebhookEndpoint:
        endpoint = WebhookEndpoint(name=name, url=url, max_retries=max_retries, owner_id=owner_id)
        self.session.add(endpoint)
        self.session.flush()
        return endpoint

    async def get_by_id(self, *, id: str | UUID, owner_id: str | UUID) -> WebhookEndpoint | None:
        stmt = select(WebhookEndpoint).where(
            WebhookEndpoint.id == id,
            WebhookEndpoint.owner_id == owner_id,
            WebhookEndpoint.deleted_at.is_(None),
        )
        return self.session.scalars(stmt).first()

    async def count(
        self,
        *,
        owner_id: str | UUID,
        status: WebhookEndpointStatus | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(WebhookEndpoint)
            .where(
                WebhookEndpoint.owner_id == owner_id,
                WebhookEndpoint.deleted_at.is_(None),
            )
        )

        if status is not None:
            stmt = stmt.where(WebhookEndpoint.status == status)

        return self.session.scalar(stmt) or 0

    async def list(
        self,
        *,
        owner_id: str | UUID,
        offset: int | None = None,
        limit: int | None = None,
        status: WebhookEndpointStatus | None = None,
    ) -> list[WebhookEndpoint]:
        stmt = select(WebhookEndpoint).where(
            WebhookEndpoint.owner_id == owner_id,
            WebhookEndpoint.deleted_at.is_(None),
        )

        if status is not None:
            stmt = stmt.where(WebhookEndpoint.status == status)

        stmt = stmt.order_by(WebhookEndpoint.created_at.desc())

        if offset is not None:
            stmt = stmt.offset(offset)

        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.scalars(stmt).all())

    async def update(
        self,
        *,
        endpoint: WebhookEndpoint,
        data: dict[str, str | int | None],
    ) -> WebhookEndpoint:
        for key, value in data.items():
            setattr(endpoint, key, value)

        self.session.flush()
        return endpoint

    async def soft_delete(self, *, endpoint: WebhookEndpoint) -> None:
        endpoint.deleted_at = datetime.now(tz=UTC)
        self.session.flush()
