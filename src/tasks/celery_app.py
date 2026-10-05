import asyncio
import concurrent.futures
import logging
from collections.abc import Coroutine
from typing import TypeVar

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from src.core.config import settings
from src.core.http_client import close_safe_http_client
from src.database.session import worker_async_engine

logger = logging.getLogger(__name__)

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

_worker_loop: asyncio.AbstractEventLoop | None = None
T = TypeVar("T")


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """Returns or creates a persistent event loop for the current Celery worker process.

    Prevents transient event loop creation/destruction per task invocation, allowing
    database connection pools and HTTP clients to remain open and reused without connection churn.
    """
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def run_in_worker_loop[T](async_coroutine: Coroutine[object, object, T]) -> T:
    """Executes an async coroutine inside the worker process's persistent event loop."""
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is not None and running_loop.is_running():
        # Defensive fallback if invoked synchronously inside an already running event loop (e.g. tests)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(async_coroutine)).result()

    loop = get_worker_loop()
    return loop.run_until_complete(async_coroutine)


@worker_process_init.connect
def on_worker_process_init(**kwargs: object) -> None:
    """Initializes persistent worker event loop when a child worker process is spawned."""
    get_worker_loop()


@worker_process_shutdown.connect
def on_worker_process_shutdown(**kwargs: object) -> None:
    """Gracefully disposes pooled database connections and HTTP client on worker shutdown."""
    global _worker_loop
    if _worker_loop and not _worker_loop.is_closed():
        try:
            _worker_loop.run_until_complete(worker_async_engine.dispose())
            _worker_loop.run_until_complete(close_safe_http_client())
        except (RuntimeError, TimeoutError, OSError) as e:
            logger.warning("Error disposing worker async resources: %s", e)
        finally:
            _worker_loop.close()
            _worker_loop = None
