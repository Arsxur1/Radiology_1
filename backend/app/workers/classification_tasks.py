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
from app.services.classification import StubClassificationModel
from app.services.segmentation import ApplicabilityRefused
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _load_model(model_version, use_stub: bool):
    if use_stub:
        return StubClassificationModel(sorted(model_version.operating_points or {}), model_version.weights_hash)
    from app.services import storage  # pragma: no cover
    from app.services.classification import TorchCXRClassifier  # pragma: no cover

    return TorchCXRClassifier(  # pragma: no cover
        model_version.weights_hash, get_settings().models_dir, storage.first_series_object
    )


def classify_with_all(db, series: Series, *, use_stub: bool) -> dict:
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
                db, series=series, model_version=mv, model=_load_model(mv, use_stub), age_years=age,
            )
            results.append({"model": f"{mv.name}@{mv.semver}", "drafts": len(out.finding_ids),
                            "shadow": out.shadow_run})
        except ApplicabilityRefused as e:
            logger.info("Серия %s вне границ применимости %s: %s", series.id, mv.name, e.reasons)
            results.append({"model": f"{mv.name}@{mv.semver}", "refused": e.reasons})
    return {"results": results}


@celery_app.task(name="classification.auto_classify_series")
def auto_classify_series(series_id: str, use_stub: bool = True) -> dict:
    db = SessionLocal()
    try:
        series = db.get(Series, uuid.UUID(series_id))
        if series is None:
            return {"skipped": "series_not_found"}
        result = classify_with_all(db, series, use_stub=use_stub)
        db.commit()
        return result
    finally:
        db.close()
