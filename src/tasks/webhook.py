import asyncio

from src.database.session import get_local_session
from src.repositories.delivery import DeliveryRepository
from src.repositories.endpoint import EndpointRepository
from src.repositories.event import EventRepository
from src.tasks.celery_app import celery_app


@celery_app.task
def deliver_webhook_task(delivery_id: str) -> None:
    from src.services.delivery import DeliveryService

    session = get_local_session()

    try:
        delivery_service = DeliveryService(
            delivery_repository=DeliveryRepository(session=session),
            event_repository=EventRepository(session=session),
            endpoint_repository=EndpointRepository(session=session),
            session=session,
        )
        asyncio.run(delivery_service.deliver(delivery_id=delivery_id))

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()
