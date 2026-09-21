import hashlib
import hmac
import secrets
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.config import settings
from src.exceptions.api_key import InvalidAPIKeyFormatError
from src.models.api_key import APIKeyEnvironment
from src.repositories.api_key import APIKeyRepository
from src.schemas.api_key import APIKeyCreateResponse, APIKeyResponse

_KEY_PREFIX = "hr"


class APIKeyService:
    def __init__(self, *, api_key_repository: APIKeyRepository, session: Session) -> None:
        self.api_key_repository = api_key_repository
        self.session = session

    def _pepper(self) -> bytes:
        return settings.api_key_pepper_value.encode()

    def _hash_secret(self, secret: str) -> str:
        return hmac.new(
            key=self._pepper(),
            msg=secret.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()

    async def create(
        self,
        *,
        owner_id: str | UUID,
        name: str,
        environment: APIKeyEnvironment = APIKeyEnvironment.TEST,
    ) -> APIKeyCreateResponse:
        # Generate a random API key
        key_id = secrets.token_hex(6)
        secret_key = secrets.token_urlsafe(32)
        key_hash = self._hash_secret(secret_key)

        constructed_api_key = f"{_KEY_PREFIX}_{environment.value}_{key_id}_{secret_key}"

        try:
            with self.session.begin_nested():
                # Store the API key in the database
                api_key = await self.api_key_repository.create(
                    owner_id=owner_id,
                    name=name,
                    key_id=key_id,
                    key_hash=key_hash,
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
                api_key=constructed_api_key,
            )

        except IntegrityError:
            self.session.rollback()
            raise

        except Exception:
            self.session.rollback()
            raise

    def parse_api_key(self, raw_key: str) -> tuple[str, str]:
        parts = raw_key.strip().split("_", 3)

        if len(parts) != 4 or parts[0] != _KEY_PREFIX or parts[1] not in APIKeyEnvironment.values():
            raise InvalidAPIKeyFormatError("Malformed API key format")

        _, _, key_id, secret_key = parts

        return key_id, secret_key

    def verify(self, secret_key: str, expected_hash: str) -> bool:
        computed_hash = self._hash_secret(secret_key)
        return hmac.compare_digest(computed_hash, expected_hash)

    async def get_by_key_id(self, *, key_id: str) -> APIKeyResponse | None:
        api_key = await self.api_key_repository.get_by_key_id(key_id=key_id)
        if api_key is None:
            return None

        return APIKeyResponse.model_validate(api_key)
