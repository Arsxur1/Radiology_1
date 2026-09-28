"""Автоматическая сегментация после приёма (ТЗ, FR-3).

Задача прогоняет серию через действующие модели и кандидатов (теневой прогон),
применяет гейт SR-7 и порождает находки (source=model, pending). Отказ по границам применимости —
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
from app.models.ml import ModelStatus
from app.services import model_registry, segmentation
from app.services.segmentation import ApplicabilityRefused, SegmentationUnavailable
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def segment_with_all(db, series: Series) -> dict:
    """Прогнать серию через ACTIVE и SHADOW модели сегментации. Вынесено для тестов.

    SHADOW — теневой прогон кандидата: находки пишутся с shadow_run=True и врачу не видны.
    Отказ по SR-7 и недоступность модели — штатные исходы по каждой модели отдельно.
    """
    versions = model_registry.models_for(
        db, task="segmentation", modality=series.modality,
        statuses=(ModelStatus.ACTIVE, ModelStatus.SHADOW),
    )
    if not versions:
        return {"skipped": "no_segmentation_model"}
    age = series.study.patient_age_years if series.study else None
    results = []
    for mv in versions:
        tag = f"{mv.name}@{mv.semver}"
        try:
            model = segmentation.load_segmentation_model(mv, series)
            out = segmentation.segment_series(db, series=series, model_version=mv, model=model, age_years=age)
            db.commit()
            results.append({"model": tag, "structures": out.structure_count,
                            "shadow": mv.status == ModelStatus.SHADOW})
        except ApplicabilityRefused as e:
            db.commit()  # факт отказа сохраняется (SR-7), результата нет
            logger.info("Серия %s вне границ применимости %s: %s", series.id, tag, e.reasons)
            results.append({"model": tag, "refused": e.reasons})
        except (SegmentationUnavailable, NotImplementedError, OSError, RuntimeError) as e:
            db.rollback()
            logger.error("Модель сегментации %s недоступна, находок нет: %s", tag, e)
            results.append({"model": tag, "error": str(e)})
        except Exception as e:  # noqa: BLE001 - сбой одной модели не мешает остальным (SR-4)
            db.rollback()
            logger.exception("Сбой модели сегментации %s", tag)
            results.append({"model": tag, "error": f"{type(e).__name__}: {e}"})
    return {"results": results}


@celery_app.task(name="segmentation.auto_segment_series")
def auto_segment_series(series_id: str) -> dict:
    """Автосегментация после приёма: действующие модели и теневой прогон кандидатов."""
    db = SessionLocal()
    try:
        series = db.get(Series, uuid.UUID(series_id))
        if series is None:
            return {"skipped": "series_not_found"}
        return segment_with_all(db, series)
    finally:
        db.close()
