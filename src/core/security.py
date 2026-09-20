from dataclasses import dataclass
from uuid import UUID

from fastapi import BackgroundTasks, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.exceptions import UnauthorizedError
from src.exceptions.api_key import InvalidAPIKeyFormatError
from src.models.api_key import APIKeyEnvironment, APIKeyStatus
from src.services.api_key import APIKeyService

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Bearer token authentication. Provide a valid API key in the Authorization header as 'Bearer <api_key>'.",
)
bearer_credentials = Depends(bearer_scheme)


@dataclass(frozen=True)
class AuthContext:
    api_key_id: UUID
    owner_id: UUID
    key_id: str
    environment: APIKeyEnvironment


async def get_auth_context_from_api_key(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    credentials: HTTPAuthorizationCredentials | None = bearer_credentials,
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Missing or invalid API key.")

    api_key_service = APIKeyService()
    try:
        # Parse the API key to extract its components
        key_id, secret_key = api_key_service.parse_api_key(credentials.credentials)
    except InvalidAPIKeyFormatError:
        raise UnauthorizedError("Invalid API key format.")

    api_key = await api_key_service.get_by_key_id(key_id=key_id)

    if api_key is None:
        raise UnauthorizedError("API key not found.")

    if not api_key_service.verify(secret_key=secret_key, expected_hash=api_key.key_hash):
        raise UnauthorizedError("Invalid API key.")

    if api_key.status != APIKeyStatus.ACTIVE:
        raise UnauthorizedError("API key is not active.")

    ctx = AuthContext(
        api_key_id=api_key.id,
        owner_id=api_key.owner_id,
        key_id=api_key.key_id,
        environment=api_key.environment,
    )
    request.auth.auth = ctx
    return ctx
