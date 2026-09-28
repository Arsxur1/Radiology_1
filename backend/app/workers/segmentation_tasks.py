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

from app.db.session import SessionLocal
from app.models.imaging import Series
from app.services import model_registry, segmentation
from app.services.classification import is_demo_weights
from app.services.inference_adapters import StubSegmentationModel
from app.services.segmentation import ApplicabilityRefused
from app.services.structure_catalog import region_for_study, structures_for_region
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="segmentation.auto_segment_series")
def auto_segment_series(series_id: str) -> dict:
    """Автоматически сегментировать серию активной моделью, если она есть."""
    db = SessionLocal()
    try:
        series = db.get(Series, uuid.UUID(series_id))
        if series is None:
            return {"skipped": "series_not_found"}

        # Только модели сегментации, заявленные для модальности серии.
        candidates = model_registry.models_for(db, task="segmentation", modality=series.modality)
        model_version = candidates[0] if candidates else None
        if model_version is None:
            # Нет допущенной модели — контур просмотра/приёма не страдает (SR-4).
            return {"skipped": "no_active_model"}

        # Заглушка — только для демо-весов: на продуктивном сервере фиктивных находок нет.
        if is_demo_weights(model_version.weights_hash):
            # Область определяется по протоколу исследования (грудь/живот/мозг).
            study = series.study
            region = region_for_study(
                study.body_part if study else None,
                study.protocol if study else None, study.description if study else None,
            ) or "CHEST"
            keys = [s.key for s in structures_for_region(region)]
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
            db.commit()  # сохраняем факт отказа для статистики (результата нет)
            return {"refused": True, "reasons": e.reasons}
        except (NotImplementedError, OSError, RuntimeError) as e:
            # Модель недоступна — черновиков нет, просмотр не страдает (SR-4).
            db.rollback()
            logger.error("Модель сегментации %s недоступна: %s", model_version.name, e)
            return {"error": str(e)}
    finally:
        db.close()
