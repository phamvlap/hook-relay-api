from src.database.session import get_async_db_context
from src.infrastructure.redis.client import get_sync_redis_client
from src.infrastructure.redis.usage_buffer import APIKeyUsageBuffer
from src.repositories.api_key import APIKeyRepository
from src.tasks.celery_app import celery_app, run_in_worker_loop


@celery_app.task()
def flush_api_key_last_used_task() -> int:
    """Scheduled Celery task that drains buffered API key usage timestamps from Redis

    and persists them to PostgreSQL in a single bulk transaction.
    """
    redis_client = get_sync_redis_client()
    usages = APIKeyUsageBuffer.drain_sync(redis_client)

    if not usages:
        return 0

    async def _flush() -> int:
        async with get_async_db_context() as session:
            repo = APIKeyRepository(session)
            return await repo.bulk_update_last_used(usages)

    return run_in_worker_loop(_flush())
