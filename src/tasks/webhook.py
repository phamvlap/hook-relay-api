from src.database.session import get_async_db_context
from src.repositories.delivery import DeliveryAttemptRepository, DeliveryRepository
from src.repositories.endpoint import EndpointRepository, EndpointSecretRepository
from src.repositories.event import EventRepository
from src.tasks.celery_app import celery_app, run_in_worker_loop


@celery_app.task
def deliver_webhook_task(delivery_id: str) -> None:
    from src.services.delivery import DeliveryService

    async def _run() -> None:
        async with get_async_db_context() as session:
            try:
                delivery_service = DeliveryService(
                    delivery_repository=DeliveryRepository(session=session),
                    delivery_attempt_repository=DeliveryAttemptRepository(session=session),
                    event_repository=EventRepository(session=session),
                    endpoint_repository=EndpointRepository(session=session),
                    endpoint_secret_repository=EndpointSecretRepository(session=session),
                    session=session,
                )
                await delivery_service.deliver(delivery_id=delivery_id)
            except Exception:
                await session.rollback()
                raise

    run_in_worker_loop(_run())


@celery_app.task
def reap_stuck_deliveries_task(timeout_seconds: int = 300, batch_size: int = 100) -> int:
    """Periodic Celery task that reaps deliveries stuck in 'delivering' status."""
    from src.services.delivery import DeliveryService

    async def _run() -> int:
        async with get_async_db_context() as session:
            try:
                delivery_service = DeliveryService(
                    delivery_repository=DeliveryRepository(session=session),
                    delivery_attempt_repository=DeliveryAttemptRepository(session=session),
                    event_repository=EventRepository(session=session),
                    endpoint_repository=EndpointRepository(session=session),
                    endpoint_secret_repository=EndpointSecretRepository(session=session),
                    session=session,
                )
                return await delivery_service.reap_stuck_deliveries(
                    timeout_seconds=timeout_seconds,
                    batch_size=batch_size,
                )
            except Exception:
                await session.rollback()
                raise

    return run_in_worker_loop(_run())
