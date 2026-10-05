"""Unit tests for Celery persistent worker event loop and lifecycle management."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.tasks.celery_app import (
    get_worker_loop,
    on_worker_process_init,
    on_worker_process_shutdown,
    run_in_worker_loop,
)


@pytest.mark.unit
class TestCeleryWorkerLoop:
    def test_get_worker_loop_returns_active_loop(self):
        """Ensures get_worker_loop creates and returns an open, active event loop."""
        loop = get_worker_loop()
        assert isinstance(loop, asyncio.AbstractEventLoop)
        assert not loop.is_closed()

    def test_get_worker_loop_is_persistent(self):
        """Ensures repeated invocations return the same event loop instance across tasks."""
        loop1 = get_worker_loop()
        loop2 = get_worker_loop()
        assert loop1 is loop2

    def test_run_in_worker_loop_executes_coroutine(self):
        """Ensures run_in_worker_loop synchronously executes and returns coroutine result."""

        async def _sample_coroutine(x: int, y: int) -> int:
            await asyncio.sleep(0.01)
            return x + y

        result = run_in_worker_loop(_sample_coroutine(10, 20))
        assert result == 30

    def test_on_worker_process_init_initializes_loop(self):
        """Ensures on_worker_process_init signal listener sets up the persistent loop."""
        on_worker_process_init()
        loop = get_worker_loop()
        assert not loop.is_closed()

    def test_on_worker_process_shutdown_cleans_up_resources(self):
        """Ensures on_worker_process_shutdown signal gracefully closes database and http resources."""
        loop = get_worker_loop()
        assert not loop.is_closed()

        mock_engine = AsyncMock()
        mock_close_http = AsyncMock()

        with (
            patch("src.tasks.celery_app.worker_async_engine", mock_engine),
            patch("src.tasks.celery_app.close_safe_http_client", mock_close_http),
        ):
            on_worker_process_shutdown()

            mock_engine.dispose.assert_awaited_once()
            mock_close_http.assert_awaited_once()
            assert loop.is_closed()
