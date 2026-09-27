from celery import Celery

from src.core.config import settings

celery_app = Celery(
    "hook_relay",
    broker=settings.redis_dsn_str,
    backend=settings.redis_dsn_str,
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
    beat_schedule={
        "flush-api-key-last-used-every-30-seconds": {
            "task": "src.tasks.api_key.flush_api_key_last_used_task",
            "schedule": 60.0,
        },
    },
)
