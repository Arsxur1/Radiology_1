"""Celery-приложение (ТЗ, раздел 4: Celery + Redis)."""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "medviz",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=["app.workers.tasks", "app.workers.segmentation_tasks", "app.workers.classification_tasks",
             "app.workers.mesh_tasks", "app.workers.registration_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=_settings.tz,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Результаты задач (идентификаторы серий, счётчики) — сутки; политика хранения.
    result_expires=86400,
)


@worker_ready.connect
def _ensure_buckets(**_kwargs) -> None:
    """Бакеты хранилища — до первой задачи приёма (на новой установке их нет)."""
    from app.services.storage import ensure_buckets_safely

    ensure_buckets_safely()
