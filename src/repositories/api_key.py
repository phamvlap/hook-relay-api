from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

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

    async def get_by_key_id(self, *, key_id: str) -> APIKey | None:
        stmt = (
            select(APIKey)
            .where(
                APIKey.key_id == key_id,
                APIKey.deleted_at.is_(None),
            )
            .options(joinedload(APIKey.owner))
        )
        return self.session.scalars(stmt).first()
