from celery import Celery

from ai_censur.config import get_broker_settings

celery_app = Celery(
    "ai_censur",
    broker=get_broker_settings().broker_url.get_secret_value(),
)

celery_app.conf.update(
    # JSON only: Celery must never unpickle data coming through the broker.
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)
