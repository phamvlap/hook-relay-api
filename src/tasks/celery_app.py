from celery import Celery

from src.core.config import settings

celery_app = Celery(
    "hook_relay",
    broker=str(settings.redis_dsn),
    backend=str(settings.redis_dsn),
)

celery_app.conf.update(
    worker_pool_restarts=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_soft_time_limit=180,  # 180 seconds for soft time limit
    task_time_limit=300,  # 300 seconds for task execution
    task_default_retry_delay=5,  # 5 seconds before retry
    task_max_retries=3,
    imports=["src.tasks"],  # Import tasks from the general module
)
