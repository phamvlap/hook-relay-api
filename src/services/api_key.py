import hashlib
import hmac
import secrets

from src.core.config import settings
from src.models.api_key import APIKeyEnvironment
from src.repositories.api_key import APIKeyRepository
from src.schemas.api_key import APIKeyCreateResponse

_KEY_PREFIX = "hr"


class APIKeyService:
    def __init__(self, *, api_key_repository: APIKeyRepository | None = None):
        self.api_key_repository = api_key_repository or APIKeyRepository()

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
        owner_id: str,
        name: str,
        environment: APIKeyEnvironment = APIKeyEnvironment.TEST,
    ) -> APIKeyCreateResponse:
        # Generate a random API key
        key_id = secrets.token_hex(6)
        secret_key = secrets.token_urlsafe(32)
        key_hash = self._hash_secret(secret_key)

        constructed_api_key = f"{_KEY_PREFIX}_{environment.value}_{key_id}_{secret_key}"

        # Store the API key in the database
        api_key = await self.api_key_repository.create(
            owner_id=owner_id,
            name=name,
            key_id=key_id,
            key_hash=key_hash,
            environment=environment,
        )

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
