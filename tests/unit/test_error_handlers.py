"""Unit tests for FastAPI exception handlers and unhandled exception logging."""

import inspect
import logging
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.core.context import AuthContext
from src.core.error_handlers import register_exception_handlers
from src.models.api_key import APIKeyEnvironment


@pytest.fixture
def test_app() -> FastAPI:
    """Creates a standalone FastAPI test app with registered exception handlers."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/trigger-unhandled")
    async def trigger_unhandled():
        raise RuntimeError("Unexpected failure in service layer")

    return app


@pytest.mark.unit
class TestUnhandledExceptionHandler:
    async def test_unhandled_exception_handler_logs_structured_error_and_returns_500(self, mocker):
        mock_logger = mocker.patch("src.core.error_handlers.logger")

        # Create dummy request
        mock_request = MagicMock(spec=Request)
        mock_request.method = "POST"
        mock_request.url = MagicMock()
        mock_request.url.path = "/api/v1/events"
        mock_request.client = MagicMock()
        mock_request.client.host = "192.168.1.50"
        owner_id = uuid4()
        mock_request.state = MagicMock()
        mock_request.state.auth = AuthContext(
            api_key_id=uuid4(),
            owner_id=owner_id,
            key_id="testkey123",
            environment=APIKeyEnvironment.TEST,
        )

        # Create FastAPI app and retrieve the registered handler
        app = FastAPI()
        register_exception_handlers(app)
        handler = app.exception_handlers[Exception]

        exc = ValueError("Simulated unexpected value error")

        result = handler(mock_request, exc)
        response = await result if inspect.isawaitable(result) else result

        assert response.status_code == 500
        assert response.body is not None

        # Verify logger.exception was called with structured context
        assert mock_logger.exception.called
        call_args, call_kwargs = mock_logger.exception.call_args
        msg = call_args[0]
        assert "Unhandled exception occurred while processing %s %s" in msg
        assert call_args[1] == "POST"
        assert call_args[2] == "/api/v1/events"
        assert call_args[3] == exc

        extra = call_kwargs.get("extra", {})
        assert extra["http_method"] == "POST"
        assert extra["http_path"] == "/api/v1/events"
        assert extra["client_ip"] == "192.168.1.50"
        assert extra["error_type"] == "ValueError"
        assert extra["owner_id"] == str(owner_id)

    async def test_unhandled_exception_handler_resilient_to_malformed_request(self, mocker):
        mock_logger = mocker.patch("src.core.error_handlers.logger")

        # Request where attribute access might raise or be absent
        broken_request = MagicMock()
        del broken_request.method
        del broken_request.url
        del broken_request.client
        broken_request.headers = {}
        broken_request.state = None

        app = FastAPI()
        register_exception_handlers(app)
        handler = app.exception_handlers[Exception]

        exc = ZeroDivisionError("division by zero")

        result = handler(broken_request, exc)
        response = await result if inspect.isawaitable(result) else result

        assert response.status_code == 500
        assert mock_logger.exception.called


@pytest.mark.unit
class TestUnhandledExceptionIntegration:
    def test_client_receives_safe_500_without_internal_leak(self, test_app: FastAPI, caplog):
        client = TestClient(test_app, raise_server_exceptions=False)

        with caplog.at_level(logging.ERROR):
            response = client.get("/trigger-unhandled")

        assert response.status_code == 500
        data = response.json()

        # Check response envelope
        assert "error" in data
        assert data["error"]["message"] == "An unexpected error occurred."
        assert data["error"]["details"] == {}
        # Ensure sensitive exception message is not leaked in the HTTP response
        assert "Unexpected failure in service layer" not in response.text

        # Verify that the log was recorded with traceback
        matching_records = [
            record
            for record in caplog.records
            if "Unhandled exception occurred while processing GET /trigger-unhandled"
            in record.message
        ]
        assert len(matching_records) == 1
        record = matching_records[0]
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None
        assert "RuntimeError: Unexpected failure in service layer" in caplog.text
