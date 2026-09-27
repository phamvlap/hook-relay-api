import json
from dataclasses import dataclass
from uuid import UUID

from src.models.api_key import APIKeyEnvironment, APIKeyStatus


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Represents the authenticated principal (API key & tenant identity)

    for the current request execution lifecycle.
    """

    api_key_id: UUID
    owner_id: UUID | str
    key_id: str
    environment: APIKeyEnvironment


@dataclass(frozen=True, slots=True)
class APIKeyAuthData:
    """Internal authentication and verification DTO shared across database queries,

    cache tiers (L1 in-memory and L2 Redis), and security verification.
    """

    api_key_id: UUID
    owner_id: UUID
    key_id: str
    key_hash: str
    status: APIKeyStatus
    environment: APIKeyEnvironment

    def to_auth_context(self) -> AuthContext:
        """Converts internal verification data to the public execution AuthContext."""
        return AuthContext(
            api_key_id=self.api_key_id,
            owner_id=self.owner_id,
            key_id=self.key_id,
            environment=self.environment,
        )

    def to_json(self) -> str:
        """Serializes auth data to JSON string for Redis caching."""
        return json.dumps(
            {
                "api_key_id": str(self.api_key_id),
                "owner_id": str(self.owner_id),
                "key_id": self.key_id,
                "key_hash": self.key_hash,
                "status": self.status.value,
                "environment": self.environment.value,
            }
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> "APIKeyAuthData | None":
        """Deserializes JSON payload from Redis into APIKeyAuthData."""
        try:
            json_data = json.loads(payload)
            return cls(
                api_key_id=UUID(json_data["api_key_id"]),
                owner_id=UUID(json_data["owner_id"]),
                key_id=json_data["key_id"],
                key_hash=json_data["key_hash"],
                status=APIKeyStatus(json_data["status"]),
                environment=APIKeyEnvironment(json_data["environment"]),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
