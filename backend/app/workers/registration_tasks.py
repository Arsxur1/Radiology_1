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


@celery_app.task(name="registration.publish")
def publish_registered_series(registration_id: str) -> dict:  # pragma: no cover - нужны SimpleITK, S3, Orthanc
    """Совмещённая серия (moving на сетке fixed) → обезличенный Orthanc и копия в S3."""
    import io
    import tempfile
    from pathlib import Path

    import pydicom
    import SimpleITK as sitk

    from app.core.config import get_settings
    from app.models.imaging import Series
    from app.models.registration import Registration, RegistrationReview
    from app.services import storage
    from app.services.orthanc import clean_client
    from app.services.registration_engines import read_series
    from app.services.registration_publish import dataset_bytes, resampled_series

    bucket = get_settings().bucket_masks
    with SessionLocal() as db:
        reg = db.get(Registration, uuid.UUID(registration_id))
        if reg is None or reg.review_status != RegistrationReview.APPROVED or not reg.transform_ref:
            return {"error": "not_approved"}
        fixed_s, moving_s = db.get(Series, reg.fixed_series_id), db.get(Series, reg.moving_series_id)
        try:
            fixed_objs = storage.series_objects(fixed_s.object_prefix or fixed_s.series_instance_uid)
            moving_objs = storage.series_objects(moving_s.object_prefix or moving_s.series_instance_uid)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "t.tfm"
                path.write_bytes(storage.get_object_ref(reg.transform_ref))
                transform = sitk.ReadTransform(str(path))
            template = pydicom.dcmread(io.BytesIO(fixed_objs[0]), stop_before_pixels=True)
            datasets = resampled_series(
                read_series(fixed_objs), read_series(moving_objs), transform, template,
                registration_id=str(reg.id), modality=moving_s.modality,
                description=f"{moving_s.modality} совмещено ({reg.stage.value}), подтверждено врачом",
            )
            client = clean_client()
            try:
                for ds in datasets:
                    data = dataset_bytes(ds)
                    storage.put_object(bucket, f"registered/{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/"
                                               f"{ds.SOPInstanceUID}.dcm", data)
                    client.upload_dicom(data)
            finally:
                client.close()
            state = {"status": "done", "series_instance_uid": str(datasets[0].SeriesInstanceUID),
                     "instances": len(datasets)}
        except Exception as e:  # noqa: BLE001 - сбой публикации не ломает совмещение (SR-4)
            logger.exception("Публикация совмещения %s не удалась", registration_id)
            state = {"status": "failed", "error": str(e)[:300]}
        reg.quality = {**(reg.quality or {}), "published": state}
        db.commit()
        return state
