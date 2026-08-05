"""Автоматическая сегментация после приёма (ТЗ, FR-3).

Задача выбирает активную модель для модальности/области, применяет гейт SR-7 и
порождает находки (source=model, pending). Отказ по границам применимости —
штатный исход: результат не пишется, причина логируется/аудируется.

На стенде без GPU используется детерминированная заглушка; реальный адаптер
подключается через настройку. Автозапуск включается, когда для модальности
существует активная модель (иначе задача — no-op).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.imaging import Series
from app.models.ml import ModelStatus, ModelVersion
from app.services import segmentation
from app.services.inference_adapters import StubSegmentationModel
from app.services.segmentation import ApplicabilityRefused
from app.services.structure_catalog import structures_for_region
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="segmentation.auto_segment_series")
def auto_segment_series(series_id: str, use_stub: bool = True) -> dict:
    """Автоматически сегментировать серию активной моделью, если она есть."""
    db = SessionLocal()
    try:
        series = db.get(Series, uuid.UUID(series_id))
        if series is None:
            return {"skipped": "series_not_found"}

        model_version = db.execute(
            select(ModelVersion).where(ModelVersion.status == ModelStatus.ACTIVE)
        ).scalars().first()
        if model_version is None:
            # Нет допущенной модели — контур просмотра/приёма не страдает (SR-4).
            return {"skipped": "no_active_model"}

        if use_stub:
            keys = [s.key for s in structures_for_region("CHEST")]
            model = StubSegmentationModel(keys, weights_hash=model_version.weights_hash)
        else:  # pragma: no cover
            from app.services.inference_adapters import TotalSegmentatorAdapter

            model = TotalSegmentatorAdapter(weights_hash=model_version.weights_hash)

        # Возраст пациента нужен для границ применимости (SR-7).
        age_years = series.study.patient_age_years if series.study else None

        try:
            outcome = segmentation.segment_series(
                db, series=series, model_version=model_version, model=model,
                age_years=age_years,
            )
            db.commit()
            return {"structure_count": outcome.structure_count}
        except ApplicabilityRefused as e:
            # SR-7: явный отказ, результат не пишется.
            logger.info("Серия %s вне границ применимости: %s", series_id, e.reasons)
            return {"refused": True, "reasons": e.reasons}
    finally:
        db.close()
