from datetime import datetime
from uuid import UUID

from sqlalchemy import column, select, update, values
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.api_key import APIKey, APIKeyEnvironment


class APIKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        owner_id: str | UUID,
        name: str,
        key_id: str,
        key_hash: str,
        environment: APIKeyEnvironment = APIKeyEnvironment.TEST,
    ) -> APIKey:
        api_key = APIKey(
            owner_id=owner_id,
            name=name,
            key_id=key_id,
            key_hash=key_hash,
            environment=environment,
        )
        self.session.add(api_key)
        await self.session.flush()
        return api_key

    async def get_by_key_id(self, *, key_id: str) -> APIKey | None:
        """Retrieves an API key by its key ID."""
        stmt = select(APIKey).where(
            APIKey.key_id == key_id,
            APIKey.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def bulk_update_last_used(self, usages: dict[str, datetime]) -> int:
        """Bulk updates last_used_at timestamp for multiple API keys in a single query."""
        if not usages:
            return 0

        update_values = values(
            column("key_id", APIKey.key_id.type),
            column("last_used_at", APIKey.last_used_at.type),
            name="update_last_used_at_values",
        ).data(list(usages.items()))

        stmt = (
            update(APIKey)
            .where(APIKey.key_id == update_values.c.key_id)
            .values(last_used_at=update_values.c.last_used_at)
        )

        result = await self.session.execute(stmt)
        await self.session.flush()

        return result.rowcount  # type: ignore
