"""Celery-приложение (ТЗ, раздел 4: Celery + Redis)."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "medviz",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=_settings.tz,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
