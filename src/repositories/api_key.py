from sqlalchemy.orm import Session, selectinload

from src.core.config import settings
from src.database.session import get_local_session
from src.models.api_key import APIKey, APIKeyEnvironment


class APIKeyRepository:
    def __init__(self, session: Session | None = None):
        if session is None:
            session = get_local_session(settings.postgres_dsn_str)
        self.session = session

    async def create(
        self,
        *,
        owner_id: str,
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
        self.session.commit()
        self.session.refresh(api_key)
        return api_key

    async def get_by_key_id(self, *, key_id: str) -> APIKey | None:
        return (
            self.session.query(APIKey)
            .filter_by(key_id=key_id, deleted_at=None)
            .options(selectinload(APIKey.owner))
            .first()
        )
