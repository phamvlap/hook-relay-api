"""Unit tests for Hook Relay CLI commands and workflows using standard mocks."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import orjson
import pytest
from typer.testing import CliRunner

from src.cli import _execute_create_owner, app
from src.models.api_key import APIKeyEnvironment, APIKeyStatus
from src.schemas.api_key import APIKeyCreateResponse
from src.schemas.owner import OwnerCreateResponse

runner = CliRunner()


@pytest.fixture
def mock_owner_response() -> OwnerCreateResponse:
    return OwnerCreateResponse(
        id=uuid4(),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_api_key_response(mock_owner_response: OwnerCreateResponse) -> APIKeyCreateResponse:
    return APIKeyCreateResponse(
        id=uuid4(),
        owner_id=mock_owner_response.id,
        name="production-backend",
        key_id="k_test_1234567890",
        status=APIKeyStatus.ACTIVE,
        environment=APIKeyEnvironment.TEST,
        last_used_at=None,
        revoked_at=None,
        api_key="hr_test_1234567890_abcdef1234567890",
    )


@pytest.mark.unit
class TestCLICreateOwnerCommand:
    """Unit tests for CLI presentation, option parsing, and exit codes."""

    def test_create_owner_success_rich_output(
        self,
        mock_owner_response: OwnerCreateResponse,
        mock_api_key_response: APIKeyCreateResponse,
    ):
        with patch("src.cli._execute_create_owner", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (mock_owner_response, mock_api_key_response)

            result = runner.invoke(
                app, ["create-owner", "--name", "production-backend", "--env", "test"]
            )

            assert result.exit_code == 0
            assert str(mock_owner_response.id) in result.output
            assert mock_api_key_response.key_id in result.output
            assert mock_api_key_response.api_key in result.output
            assert "Owner & API Key Created Successfully" in result.output
            mock_exec.assert_awaited_once_with(
                name="production-backend", environment=APIKeyEnvironment.TEST
            )

    def test_create_owner_hierarchical_subcommand_alias(
        self,
        mock_owner_response: OwnerCreateResponse,
        mock_api_key_response: APIKeyCreateResponse,
    ):
        with patch("src.cli._execute_create_owner", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (mock_owner_response, mock_api_key_response)

            result = runner.invoke(app, ["owner", "create", "--name", "production-backend"])

            assert result.exit_code == 0
            assert str(mock_owner_response.id) in result.output
            mock_exec.assert_awaited_once_with(
                name="production-backend", environment=APIKeyEnvironment.TEST
            )

    def test_create_owner_json_output(
        self,
        mock_owner_response: OwnerCreateResponse,
        mock_api_key_response: APIKeyCreateResponse,
    ):
        with patch("src.cli._execute_create_owner", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (mock_owner_response, mock_api_key_response)

            result = runner.invoke(app, ["create-owner", "--name", "production-backend", "--json"])

            assert result.exit_code == 0
            data = orjson.loads(result.output)

            assert data["owner"]["id"] == str(mock_owner_response.id)
            assert data["api_key"]["key_id"] == mock_api_key_response.key_id
            assert data["api_key"]["api_key"] == mock_api_key_response.api_key
            assert data["api_key"]["environment"] == "test"
            assert data["api_key"]["status"] == "active"

    def test_create_owner_live_environment_option(
        self,
        mock_owner_response: OwnerCreateResponse,
        mock_api_key_response: APIKeyCreateResponse,
    ):
        mock_api_key_response.environment = APIKeyEnvironment.LIVE
        with patch("src.cli._execute_create_owner", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (mock_owner_response, mock_api_key_response)

            result = runner.invoke(
                app, ["create-owner", "--name", "production-backend", "--env", "live"]
            )

            assert result.exit_code == 0
            mock_exec.assert_awaited_once_with(
                name="production-backend", environment=APIKeyEnvironment.LIVE
            )

    def test_create_owner_missing_required_name_fails(self):
        result = runner.invoke(app, ["create-owner"])

        assert result.exit_code == 2
        assert "Missing option '--name'" in result.output or "Missing option '-n'" in result.output

    def test_create_owner_invalid_env_fails(self):
        result = runner.invoke(app, ["create-owner", "--name", "demo", "--env", "invalid_env"])

        assert result.exit_code == 2
        assert "Invalid value for '--env'" in result.output or "-e" in result.output

    def test_create_owner_execution_failure_renders_error(self):
        with patch("src.cli._execute_create_owner", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = RuntimeError("Database unreachable")

            result = runner.invoke(app, ["create-owner", "--name", "demo"])

            assert result.exit_code == 1
            assert "Error: Failed to create owner: Database unreachable" in result.output

    def test_create_owner_execution_failure_json_output(self):
        with patch("src.cli._execute_create_owner", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = RuntimeError("Unique violation")

            result = runner.invoke(app, ["create-owner", "--name", "demo", "--json"])

            assert result.exit_code == 1
            error_payload = orjson.loads(result.output)
            assert error_payload == {"error": "Unique violation"}


@pytest.mark.unit
class TestCLIExecuteCreateOwnerWorkflow:
    """Unit tests for the underlying service & database interaction in _execute_create_owner."""

    async def test_execute_create_owner_invokes_services_within_db_context(
        self,
        mock_owner_response: OwnerCreateResponse,
        mock_api_key_response: APIKeyCreateResponse,
    ):
        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_owner_service = MagicMock()
        mock_owner_service.create = AsyncMock(return_value=mock_owner_response)

        mock_api_key_service = MagicMock()
        mock_api_key_service.create = AsyncMock(return_value=mock_api_key_response)

        with (
            patch("src.cli.get_async_db_context", return_value=mock_ctx) as mock_db_ctx,
            patch("src.cli.OwnerRepository") as mock_owner_repo_cls,
            patch(
                "src.cli.OwnerService", return_value=mock_owner_service
            ) as mock_owner_service_cls,
            patch("src.cli.APIKeyRepository") as mock_api_key_repo_cls,
            patch(
                "src.cli.APIKeyService", return_value=mock_api_key_service
            ) as mock_api_key_service_cls,
        ):
            owner, api_key = await _execute_create_owner(
                name="service-test",
                environment=APIKeyEnvironment.TEST,
            )

            # Assert context manager entered
            mock_db_ctx.assert_called_once()
            mock_ctx.__aenter__.assert_awaited_once()

            # Assert repositories instantiated with session
            mock_owner_repo_cls.assert_called_once_with(mock_session)
            mock_api_key_repo_cls.assert_called_once_with(mock_session)

            # Assert services instantiated with repository and session
            mock_owner_service_cls.assert_called_once_with(
                owner_repository=mock_owner_repo_cls.return_value,
                session=mock_session,
            )
            mock_api_key_service_cls.assert_called_once_with(
                api_key_repository=mock_api_key_repo_cls.return_value,
                session=mock_session,
            )

            # Assert domain services called
            mock_owner_service.create.assert_awaited_once()
            mock_api_key_service.create.assert_awaited_once_with(
                owner_id=str(mock_owner_response.id),
                name="service-test",
                environment=APIKeyEnvironment.TEST,
            )

            assert owner == mock_owner_response
            assert api_key == mock_api_key_response
