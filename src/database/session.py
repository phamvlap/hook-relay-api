from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings

# Disable asyncpg & SQLAlchemy statement caching when configured (e.g., PgBouncer/Supabase transaction pooling)
_ASYNCPG_CONNECT_ARGS = {
    "statement_cache_size": settings.db_statement_cache_size,
    "prepared_statement_cache_size": settings.db_statement_cache_size,
}

# Create a SQLAlchemy engine and session factory for synchronous operations (migrations, CLI, scripts)
engine: Engine = create_engine(
    settings.postgres_dsn_str,
    pool_size=settings.db_sync_pool_size,
    max_overflow=settings.db_sync_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=settings.db_pool_pre_ping,
    echo=settings.db_echo,
)

# Create a SQLAlchemy async engine and session factory for the main FastAPI request lifecycle
async_engine: AsyncEngine = create_async_engine(
    settings.postgres_async_dsn_str,
    pool_size=settings.db_async_pool_size,
    max_overflow=settings.db_async_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=settings.db_pool_pre_ping,
    echo=settings.db_echo,
    connect_args=_ASYNCPG_CONNECT_ARGS,
)

# Async engine for Celery tasks, CLI commands, and background processes
# Pooled with dedicated connection bounds to prevent connection churn across worker tasks
worker_async_engine: AsyncEngine = create_async_engine(
    settings.postgres_async_dsn_str,
    pool_size=settings.db_worker_pool_size,
    max_overflow=settings.db_worker_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=settings.db_pool_pre_ping,
    echo=settings.db_echo,
    connect_args=_ASYNCPG_CONNECT_ARGS,
)

# Session factory for creating new sessions
LocalSession = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


# Session factory for creating new async sessions
AsyncLocalSession = async_sessionmaker(
    bind=async_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

# Session factory for Celery workers & background tasks (fresh connection per session)
WorkerAsyncLocalSession = async_sessionmaker(
    bind=worker_async_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


def get_local_session() -> Session:
    return LocalSession()


def get_async_local_session() -> AsyncSession:
    return AsyncLocalSession()


@contextmanager
def get_db_context() -> Generator[Session]:
    """Provides a transactional database session context manager for Celery workers & scripts."""
    session = LocalSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def get_async_db_context() -> AsyncGenerator[AsyncSession]:
    """Provides a transactional database session context manager for Celery workers & scripts."""
    session = WorkerAsyncLocalSession()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
