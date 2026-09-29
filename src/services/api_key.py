from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.api_key import APIKeyEnvironment
from src.repositories.api_key import APIKeyRepository
from src.schemas.api_key import APIKeyCreateResponse
from src.utils.api_key import generate_api_key


class APIKeyService:
    def __init__(self, *, api_key_repository: APIKeyRepository, session: Session) -> None:
        self.api_key_repository = api_key_repository
        self.session = session

    async def create(
        self,
        *,
        owner_id: str | UUID,
        name: str,
        environment: APIKeyEnvironment = APIKeyEnvironment.TEST,
    ) -> APIKeyCreateResponse:
        # Generate a random API key using centralized crypto utility
        generated_key = generate_api_key(environment)

        try:
            with self.session.begin_nested():
                api_key = await self.api_key_repository.create(
                    owner_id=owner_id,
                    name=name,
                    key_id=generated_key.key_id,
                    key_hash=generated_key.key_hash,
                    environment=environment,
                )

            self.session.commit()
            return APIKeyCreateResponse(
                id=api_key.id,
                owner_id=api_key.owner_id,
                name=api_key.name,
                key_id=api_key.key_id,
                status=api_key.status,
                environment=api_key.environment,
                last_used_at=api_key.last_used_at,
                revoked_at=api_key.revoked_at,
                api_key=generated_key.full_key,
            )

        except IntegrityError:
            self.session.rollback()
            raise

        except Exception:
            self.session.rollback()
            raise
