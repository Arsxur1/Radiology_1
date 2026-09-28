"""Задачи приёма (ТЗ, FR-1). Обезличивание и зеркалирование в фоне."""

from __future__ import annotations

import io
import logging

from app.core.config import get_settings
from app.db.session import IdMapSessionLocal, SessionLocal
from app.services import ingest, storage
from app.services.anonymization import anonymize_dataset
from app.services.orthanc import clean_client, raw_client
from app.workers.celery_app import celery_app
from app.workers.dicom_meta import extract_series_meta, extract_study_meta

logger = logging.getLogger(__name__)


def _drop_raw(raw, raw_instance_id: str, enabled: bool) -> bool:
    """Удалить исходник с PHI из orthanc-raw после фиксации результата в БД.

    Ошибка удаления не ломает приём: снимок уже обезличен и сохранён; остаток
    уберёт повторный прогон или администратор.
    """
    if not enabled:
        return False
    try:
        raw.delete_instance(raw_instance_id)
        return True
    except Exception:  # noqa: BLE001
        logger.warning("Не удалось удалить исходник %s из orthanc-raw", raw_instance_id, exc_info=True)
        return False


def _schedule_analysis(series_id: str, settings) -> None:
    from app.workers import analysis_debounce

    store = analysis_debounce.RedisStore(settings.redis_url)
    analysis_debounce.schedule(
        store, series_id,
        lambda sid, token: analyze_series.apply_async((sid, token), countdown=settings.analysis_delay_seconds),
    )


@celery_app.task(name="ingest.analyze_series")
def analyze_series(series_id: str, token: str) -> dict:
    """Автоанализ серии (FR-3): сегментация и классификация. No-op без подходящих моделей."""
    from app.workers import analysis_debounce

    if not analysis_debounce.is_last(analysis_debounce.RedisStore(get_settings().redis_url), series_id, token):
        return {"skipped": "newer_instance_arrived"}
    from app.workers.classification_tasks import auto_classify_series
    from app.workers.segmentation_tasks import auto_segment_series

    auto_segment_series.delay(series_id)
    auto_classify_series.delay(series_id)
    return {"scheduled": series_id}


@celery_app.task(name="ingest.process_raw_instance", bind=True, max_retries=3)
def process_raw_instance(self, raw_instance_id: str) -> dict:
    """Обработать один инстанс из raw-Orthanc: обезличить и зеркалировать.

    Пиксели обезличенного объекта → clean-Orthanc + MinIO. Метаданные → PostgreSQL.
    Идентифицирующие данные → идентифицирующий контур.
    """
    import pydicom

    settings = get_settings()
    raw = raw_client()
    clean = clean_client()
    try:
        raw_bytes = raw.get_instance_file(raw_instance_id)
        ds = pydicom.dcmread(io.BytesIO(raw_bytes))

        clean_ds, plan = anonymize_dataset(ds)

        buf = io.BytesIO()
        clean_ds.save_as(buf, write_like_original=False)
        clean_bytes = buf.getvalue()

        # Обезличенный объект — в clean-Orthanc и MinIO (пиксели не в БД).
        clean.upload_dicom(clean_bytes)
        object_key = f"{plan.pseudonym_study_uid}/{clean_ds.SeriesInstanceUID}/{clean_ds.SOPInstanceUID}.dcm"
        storage.put_object(settings.bucket_images, object_key, clean_bytes)

        tags = {elem.keyword: str(elem.value) for elem in clean_ds if elem.keyword}
        study_meta = extract_study_meta(tags)
        series_meta = extract_series_meta(tags)
        series_meta["object_prefix"] = f"{plan.pseudonym_study_uid}/{clean_ds.SeriesInstanceUID}"

        db = SessionLocal()
        idmap = IdMapSessionLocal()
        try:
            outcome = ingest.persist_ingest(
                db, idmap, plan=plan, study_meta=study_meta, series_meta=series_meta
            )
            db.commit()
            _drop_raw(raw, raw_instance_id, settings.raw_delete_after_ingest)
            # Автоанализ — когда серия пришла целиком: каждый срез переносит запуск.
            _schedule_analysis(str(outcome.series_id), settings)
            return {
                "series_id": str(outcome.series_id),
                "duplicate": outcome.duplicate,
                "needs_manual_link": outcome.needs_manual_link,
            }
        finally:
            db.close()
            idmap.close()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка обработки инстанса %s", raw_instance_id)
        raise self.retry(exc=exc, countdown=10) from exc
    finally:
        raw.close()
        clean.close()
