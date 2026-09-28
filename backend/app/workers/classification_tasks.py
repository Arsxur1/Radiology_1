"""Автоматическая классификация находок после приёма (FR-10, раздел 2).

Для серии запускаются все подходящие модели классификации:
  - ACTIVE — результат идёт врачу (с учётом режима установки);
  - SHADOW — теневой прогон кандидата: результат пишется с shadow_run=True и
    врачу не показывается, но участвует в сравнении с заключениями (FR-10 п. 5).
Отказ по границам применимости — штатный исход, результат не пишется (SR-7).
"""

from __future__ import annotations

import logging
import uuid

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.imaging import Series
from app.models.ml import ModelStatus
from app.services import classification, model_registry
from app.services.classification import ModelUnavailable
from app.services.segmentation import ApplicabilityRefused
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _store_heatmap(key: str, data: bytes) -> str:  # pragma: no cover - нужен MinIO
    from app.services import storage

    return storage.put_object(get_settings().bucket_masks, key, data, content_type="image/png")


def classify_with_all(db, series: Series, *, store_artifact=None) -> dict:
    """Прогнать серию через ACTIVE и SHADOW классификаторы. Вынесено для тестов."""
    versions = model_registry.models_for(
        db, task="classification", modality=series.modality,
        statuses=(ModelStatus.ACTIVE, ModelStatus.SHADOW),
    )
    if not versions:
        return {"skipped": "no_classification_model"}
    age = series.study.patient_age_years if series.study else None
    results = []
    for mv in versions:
        try:
            out = classification.classify_series(
                db, series=series, model_version=mv, model=classification.load_model(mv), age_years=age,
                store_artifact=store_artifact,
            )
            results.append({"model": f"{mv.name}@{mv.semver}", "drafts": len(out.finding_ids),
                            "shadow": out.shadow_run})
        except ApplicabilityRefused as e:
            logger.info("Серия %s вне границ применимости %s: %s", series.id, mv.name, e.reasons)
            results.append({"model": f"{mv.name}@{mv.semver}", "refused": e.reasons})
        except ModelUnavailable as e:
            logger.error("Модель недоступна, черновики не созданы: %s", e)
            results.append({"model": f"{mv.name}@{mv.semver}", "error": str(e)})
        except Exception as e:  # noqa: BLE001 - сбой одной модели не мешает остальным (SR-4)
            db.rollback()
            logger.exception("Сбой модели классификации %s", mv.name)
            results.append({"model": f"{mv.name}@{mv.semver}", "error": f"{type(e).__name__}: {e}"})
    return {"results": results}


@celery_app.task(name="classification.auto_classify_series")
def auto_classify_series(series_id: str) -> dict:
    db = SessionLocal()
    try:
        series = db.get(Series, uuid.UUID(series_id))
        if series is None:
            return {"skipped": "series_not_found"}
        result = classify_with_all(db, series, store_artifact=_store_heatmap)
        db.commit()
        return result
    finally:
        db.close()
