"""Unit tests for database session configuration and PgBouncer compatibility."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from src.database.session import (
    _ASYNCPG_CONNECT_ARGS,
    async_engine,
    get_async_db_context,
    worker_async_engine,
)


@pytest.mark.unit
class TestDatabaseSessionConfiguration:
    def test_asyncpg_connect_args_disables_prepared_statement_cache(self):
        """Statement caching must be disabled for full PgBouncer transaction pooling compatibility."""
        assert _ASYNCPG_CONNECT_ARGS["statement_cache_size"] == 0
        assert _ASYNCPG_CONNECT_ARGS["prepared_statement_cache_size"] == 0

    def test_engines_contain_disabled_statement_cache_connect_args(self):
        """Both web async_engine and worker_async_engine must have statement_cache_size=0 configured."""
        for engine in (async_engine, worker_async_engine):
            # Check the connect_args of the engine
            connect_args = engine.url.query
            # Either via dialect connect_args or URL query
            dialect_args = getattr(engine.dialect, "connect_args", {})
            assert (
                dialect_args.get("statement_cache_size") == 0
                or _ASYNCPG_CONNECT_ARGS.get("statement_cache_size") == 0
            )

    def test_worker_engine_uses_null_pool(self):
        """Worker engine used by Celery tasks and CLI commands must use NullPool to avoid cross-loop errors."""
        assert isinstance(worker_async_engine.pool, NullPool)


@pytest.mark.integration
class TestWorkerAsyncEngineExecution:
    def test_consecutive_asyncio_run_calls_do_not_conflict(self):
        """Simulate sequential Celery task runs each invoking asyncio.run().

        Verifies that no cross-loop Future/transport errors or DuplicatePreparedStatementError occurs.
        """

        def _execute_task():
            async def _task():
                async with get_async_db_context() as session:
                    res = await session.execute(text("SELECT 1"))
                    return res.scalar()

            return asyncio.run(_task())

        result_1 = _execute_task()
        result_2 = _execute_task()
        result_3 = _execute_task()

        assert result_1 == 1
        assert result_2 == 1
        assert result_3 == 1
