import asyncio

from src.tasks.celery_app import celery_app


@celery_app.task
def deliver_webhook_task(delivery_id: str) -> None:
    from src.services.delivery import DeliveryService

    delivery_service = DeliveryService()
    asyncio.run(delivery_service.deliver(delivery_id=delivery_id))
