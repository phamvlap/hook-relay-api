"""Unit tests for AuthContext and APIKeyAuthData serialization and conversions."""

from uuid import uuid4

import pytest

from src.core.context import APIKeyAuthData, AuthContext
from src.models.api_key import APIKeyEnvironment, APIKeyStatus


@pytest.mark.unit
class TestAPIKeyAuthData:
    @pytest.fixture
    def sample_auth_data(self) -> APIKeyAuthData:
        return APIKeyAuthData(
            api_key_id=uuid4(),
            owner_id=uuid4(),
            key_id="0123456789abcdef",
            key_hash="a" * 64,
            status=APIKeyStatus.ACTIVE,
            environment=APIKeyEnvironment.LIVE,
        )

    def test_to_auth_context(self, sample_auth_data: APIKeyAuthData):
        context = sample_auth_data.to_auth_context()

        assert isinstance(context, AuthContext)
        assert context.api_key_id == sample_auth_data.api_key_id
        assert context.owner_id == sample_auth_data.owner_id
        assert context.key_id == sample_auth_data.key_id
        assert context.environment == sample_auth_data.environment

    def test_to_json_and_from_json_roundtrip(self, sample_auth_data: APIKeyAuthData):
        json_str = sample_auth_data.to_json()
        assert isinstance(json_str, str)

        restored = APIKeyAuthData.from_json(json_str)
        assert restored is not None
        assert restored.api_key_id == sample_auth_data.api_key_id
        assert restored.owner_id == sample_auth_data.owner_id
        assert restored.key_id == sample_auth_data.key_id
        assert restored.key_hash == sample_auth_data.key_hash
        assert restored.status == sample_auth_data.status
        assert restored.environment == sample_auth_data.environment

    def test_from_json_with_bytes(self, sample_auth_data: APIKeyAuthData):
        raw_bytes = sample_auth_data.to_json().encode("utf-8")
        restored = APIKeyAuthData.from_json(raw_bytes)

        assert restored is not None
        assert restored.key_id == sample_auth_data.key_id

    def test_from_json_invalid_payloads_return_none(self):
        # Malformed JSON
        assert APIKeyAuthData.from_json("invalid-json{") is None

        # Missing required keys
        assert APIKeyAuthData.from_json('{"key_id": "test"}') is None

        # Invalid UUID
        assert (
            APIKeyAuthData.from_json(
                '{"api_key_id": "not-a-uuid", "owner_id": "123", "key_id": "k", '
                '"key_hash": "h", "status": "active", "environment": "live"}'
            )
            is None
        )

        # Invalid enum values
        assert (
            APIKeyAuthData.from_json(
                '{"api_key_id": "00000000-0000-0000-0000-000000000001", '
                '"owner_id": "00000000-0000-0000-0000-000000000002", '
                '"key_id": "k", "key_hash": "h", "status": "invalid_status", "environment": "live"}'
            )
            is None
        )
