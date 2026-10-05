"""Unit tests for database session configuration and PgBouncer compatibility."""

import pytest
from sqlalchemy import text
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from src.database.session import (
    _ASYNCPG_CONNECT_ARGS,
    async_engine,
    get_async_db_context,
    worker_async_engine,
)
from src.tasks.celery_app import run_in_worker_loop


@pytest.mark.unit
class TestDatabaseSessionConfiguration:
    def test_asyncpg_connect_args_disables_prepared_statement_cache(self):
        """Statement caching must be disabled for full PgBouncer transaction pooling compatibility."""
        assert _ASYNCPG_CONNECT_ARGS["statement_cache_size"] == 0
        assert _ASYNCPG_CONNECT_ARGS["prepared_statement_cache_size"] == 0

    def test_engines_contain_disabled_statement_cache_connect_args(self):
        """Both web async_engine and worker_async_engine must have statement_cache_size=0 configured."""
        for engine in (async_engine, worker_async_engine):
            # Either via dialect connect_args or URL query
            dialect_args = getattr(engine.dialect, "connect_args", {})
            assert (
                dialect_args.get("statement_cache_size") == 0
                or _ASYNCPG_CONNECT_ARGS.get("statement_cache_size") == 0
            )

    def test_worker_engine_uses_connection_pool(self):
        """Worker engine used by Celery tasks and CLI commands must use connection pooling to avoid connection churn."""
        assert not isinstance(worker_async_engine.pool, NullPool)
        assert isinstance(worker_async_engine.pool, AsyncAdaptedQueuePool)


@pytest.mark.integration
class TestWorkerAsyncEngineExecution:
    def test_consecutive_worker_loop_tasks_reuse_connection(self):
        """Simulate sequential Celery task runs each executing within the worker's persistent event loop.

        Verifies that consecutive task runs safely reuse pooled connections without cross-loop errors.
        """

        def _execute_task():
            async def _task():
                async with get_async_db_context() as session:
                    res = await session.execute(text("SELECT 1"))
                    return res.scalar()

            return run_in_worker_loop(_task())

        result_1 = _execute_task()
        result_2 = _execute_task()
        result_3 = _execute_task()

        assert result_1 == 1
        assert result_2 == 1
        assert result_3 == 1
