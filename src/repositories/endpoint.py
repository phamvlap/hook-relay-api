from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.endpoint import (
    WebhookEndpoint,
    WebhookEndpointSecret,
    WebhookEndpointSecretStatus,
    WebhookEndpointStatus,
)


class EndpointRepository:
    def __init__(self, session: AsyncSession) -> None:
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
        await self.session.flush()
        return endpoint

    async def get_by_id(self, *, id: str | UUID, owner_id: str | UUID) -> WebhookEndpoint | None:
        stmt = select(WebhookEndpoint).where(
            WebhookEndpoint.id == id,
            WebhookEndpoint.owner_id == owner_id,
            WebhookEndpoint.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

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

        result = await self.session.execute(stmt)
        return result.scalar() or 0

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

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        *,
        endpoint: WebhookEndpoint,
        data: dict[str, str | int | None],
    ) -> WebhookEndpoint:
        for key, value in data.items():
            setattr(endpoint, key, value)

        await self.session.flush()
        return endpoint

    async def soft_delete(self, *, endpoint: WebhookEndpoint) -> None:
        endpoint.deleted_at = datetime.now(tz=UTC)
        await self.session.flush()


class EndpointSecretRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        endpoint_id: str | UUID,
        encrypted_secret: str,
        version: int = 1,
        status: WebhookEndpointSecretStatus = WebhookEndpointSecretStatus.ACTIVE,
    ) -> WebhookEndpointSecret:
        secret = WebhookEndpointSecret(
            endpoint_id=endpoint_id,
            encrypted_secret=encrypted_secret,
            version=version,
            status=status,
        )
        self.session.add(secret)
        await self.session.flush()
        return secret

    async def get_active_secret(
        self,
        *,
        endpoint_id: str | UUID,
    ) -> WebhookEndpointSecret | None:
        stmt = (
            select(WebhookEndpointSecret)
            .where(
                WebhookEndpointSecret.endpoint_id == endpoint_id,
                WebhookEndpointSecret.status == WebhookEndpointSecretStatus.ACTIVE,
                WebhookEndpointSecret.deleted_at.is_(None),
            )
            .order_by(WebhookEndpointSecret.version.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_version(
        self,
        *,
        endpoint_id: str | UUID,
        version: int,
    ) -> WebhookEndpointSecret | None:
        stmt = select(WebhookEndpointSecret).where(
            WebhookEndpointSecret.endpoint_id == endpoint_id,
            WebhookEndpointSecret.version == version,
            WebhookEndpointSecret.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_next_version(self, *, endpoint_id: str | UUID) -> int:
        stmt = select(func.max(WebhookEndpointSecret.version)).where(
            WebhookEndpointSecret.endpoint_id == endpoint_id,
            WebhookEndpointSecret.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        max_version = result.scalar()
        return (max_version or 0) + 1

    async def revoke_active_secrets(self, *, endpoint_id: str | UUID) -> None:
        now = datetime.now(tz=UTC)
        stmt = select(WebhookEndpointSecret).where(
            WebhookEndpointSecret.endpoint_id == endpoint_id,
            WebhookEndpointSecret.status == WebhookEndpointSecretStatus.ACTIVE,
            WebhookEndpointSecret.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        active_secrets = result.scalars().all()
        for secret in active_secrets:
            secret.status = WebhookEndpointSecretStatus.REVOKED
            secret.revoked_at = now
        await self.session.flush()
