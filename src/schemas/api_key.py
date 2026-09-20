from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.api_key import APIKeyEnvironment, APIKeyStatus


class APIKeyCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    key_id: str
    status: APIKeyStatus
    environment: APIKeyEnvironment
    last_used_at: datetime | None
    revoked_at: datetime | None
    api_key: str
