from src.tasks.celery_app import celery_app


@celery_app.task
def deliver_webhook_task(delivery_id: str) -> None:
    pass
