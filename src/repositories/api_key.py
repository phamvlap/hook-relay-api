from datetime import datetime
from uuid import UUID

from sqlalchemy import column, select, update, values
from sqlalchemy.orm import Session

from src.core.context import APIKeyAuthData
from src.models.api_key import APIKey, APIKeyEnvironment


class APIKeyRepository:
    def __init__(self, session: Session) -> None:
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
        self.session.flush()
        return api_key

    def get_auth_data(self, *, key_id: str) -> APIKeyAuthData | None:
        """Retrieves authentication and verification data for an API key."""
        stmt = select(APIKey).where(
            APIKey.key_id == key_id,
            APIKey.deleted_at.is_(None),
        )
        api_key = self.session.scalars(stmt).first()
        if api_key is None:
            return None

        return APIKeyAuthData(
            api_key_id=api_key.id,
            owner_id=api_key.owner_id,
            key_id=api_key.key_id,
            key_hash=api_key.key_hash,
            status=api_key.status,
            environment=api_key.environment,
        )

    def bulk_update_last_used(self, usages: dict[str, datetime]) -> int:
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

        result = self.session.execute(stmt)
        self.session.flush()

        return result.rowcount  # type: ignore
