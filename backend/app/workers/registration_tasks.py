"""Совмещение модальностей в воркере (FR-4): SimpleITK, результат — на проверку врачу."""

from __future__ import annotations

import logging
import uuid

from app.db.session import SessionLocal
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="registration.run")
def run_registration_task(registration_id: str, actor: str) -> dict:  # pragma: no cover - нужны SimpleITK и S3
    from app.core.config import get_settings
    from app.models.imaging import Series
    from app.models.registration import Registration
    from app.services import storage
    from app.services.registration import apply_output
    from app.services.registration_engines import ItkRegistrationEngine

    bucket = get_settings().bucket_masks
    with SessionLocal() as db:
        reg = db.get(Registration, uuid.UUID(registration_id))
        if reg is None:
            return {"error": "not_found"}
        requested = reg.stage
        reg.quality = {"status": "running"}
        db.commit()
        fixed, moving = db.get(Series, reg.fixed_series_id), db.get(Series, reg.moving_series_id)
        engine = ItkRegistrationEngine(
            store=lambda key, data, ctype: storage.put_object(bucket, key, data, content_type=ctype))
        try:
            output = engine.register(fixed.object_prefix or fixed.series_instance_uid,
                                     moving.object_prefix or moving.series_instance_uid, requested)
            apply_output(db, reg, output, requested=requested, actor=actor)
        except Exception as e:  # noqa: BLE001 - сбой совмещения не должен ронять воркер (SR-4)
            db.rollback()
            logger.exception("Совмещение %s не удалось", registration_id)
            reg = db.get(Registration, uuid.UUID(registration_id))
            reg.quality = {"status": "failed", "error": str(e)[:300]}
        db.commit()
        return {"status": reg.quality.get("status"), "stage": reg.stage.value}
