"""Демо-данные для показа системы без PACS и GPU (режим RESEARCH).

Создаёт обезличенного пациента, два КТ-исследования грудной клетки с сериями,
активную модель-заглушку и прогоняет сегментацию — так во фронтенде сразу видны
worklist, находки (черновик ИИ), сборка заключения и динамика во времени.

Для пилота NCMC добавляется детский рентген ОГК (DX, 6 лет): активный классификатор
находок и кандидат в SHADOW (теневой прогон — врачу не виден). С флагом
--with-storage синтетический снимок загружается в обезличенный Orthanc и MinIO,
а тепловые карты — в MinIO: во фронтенде работает «Зона внимания ИИ».

Запуск на стенде:
    docker compose exec backend python scripts/seed_demo.py --with-storage

НЕ содержит реальных данных пациентов. Не запускать на продуктивной БД с PHI.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import OperatingModeState
from app.models.imaging import Series, Study
from app.models.ml import ModelStatus, ModelVersion
from app.models.patient import Patient, PatientIdentifier
from app.services import segmentation
from app.services.inference_adapters import StubSegmentationModel
from app.services.patient_matching import identifier_value
from app.services.structure_catalog import structures_for_region

CHEST_APPLICABILITY = {
    "modality": ["CT"],
    "body_part": ["CHEST"],
    "slice_thickness_mm": {"max": 3.0},
    "age": {"min_years": 18},
    "manufacturers": ["Siemens", "GE", "Philips", "Canon"],
    "allow_lossy": False,
}


PEDS_CXR_APPLICABILITY = {
    "modality": ["CR", "DX"],
    "body_part": ["CHEST", "THORAX"],
    "age": {"min_years": 0, "max_years": 17},
    "allow_lossy": False,
}
# Пороги демо-классификатора (в реальности — из registration.json обучающего контура).
DEMO_OPERATING_POINTS = {
    code: {"threshold": t}
    for code, t in {"CXR-000": 0.5, "CXR-100": 0.5, "CXR-104": 0.45, "CXR-113": 0.5,
                    "CXR-200": 0.4, "CXR-201": 0.5, "CXR-500": 0.5, "CXR-700": 0.5}.items()
}


def _active_model(db: Session) -> ModelVersion:
    mv = db.execute(
        select(ModelVersion).where(ModelVersion.status == ModelStatus.ACTIVE,
                                   ModelVersion.task == "segmentation")
    ).scalars().first()
    if mv is None:
        mv = ModelVersion(
            name="demo_chest", semver="0.1.0", weights_hash="demo-stub",
            applicability=CHEST_APPLICABILITY, status=ModelStatus.ACTIVE,
        )
        db.add(mv)
        db.flush()
    return mv


def _study_with_series(db: Session, patient: Patient, *, uid: str, date: datetime) -> Series:
    study = Study(
        patient_id=patient.id, study_instance_uid=uid, modality="CT",
        study_date=date, description="КТ грудной клетки (демо)",
        manufacturer="Siemens", protocol="Chest CT", patient_age_years=45.0,
    )
    db.add(study)
    db.flush()
    series = Series(
        study_id=study.id, series_instance_uid=f"{uid}-s1", modality="CT",
        description="Аксиальная серия", slice_thickness_mm=1.0,
        voxel_spacing=[0.7, 0.7, 1.0], object_prefix=f"demo/{uid}",
    )
    db.add(series)
    db.flush()
    return series


def synthetic_cxr_dicom(study_uid: str, series_uid: str, sop_uid: str, size: int = 256) -> bytes:
    """Синтетический «рентген ОГК» (эллипсы: тело, лёгкие, сердце, позвоночник). Не данные пациента."""
    import io
    import struct

    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    def inside(x, y, cx, cy, rx, ry):
        return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1

    px = []
    for y in range(size):
        for x in range(size):
            u, v = x / size, y / size
            val = 200
            if inside(u, v, 0.5, 0.55, 0.46, 0.5):
                val = 2600                                   # мягкие ткани
            if inside(u, v, 0.32, 0.5, 0.14, 0.3) or inside(u, v, 0.68, 0.5, 0.14, 0.3):
                val = 900                                    # лёгкие (воздух — темнее)
            if inside(u, v, 0.56, 0.62, 0.13, 0.12):
                val = 2900                                   # сердечная тень
            if abs(u - 0.5) < 0.03:
                val = 3500                                   # позвоночник
            px.append(val + (x * 7 + y * 13) % 40)           # лёгкая «текстура»

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.1"  # Digital X-Ray for Presentation
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, sop_uid
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
    ds.Modality, ds.BodyPartExamined, ds.PatientAge = "DX", "CHEST", "006Y"
    ds.PatientID, ds.PatientName = "DEMO", "DEMO^CXR"
    ds.Rows = ds.Columns = size
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
    ds.WindowCenter, ds.WindowWidth = 2000, 3800
    ds.PixelData = struct.pack(f"<{len(px)}H", *px)
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def _seed_pediatric_cxr(db: Session, patient: Patient, *, with_storage: bool) -> dict:
    """Детский рентген ОГК: активный классификатор + кандидат в теневом прогоне."""
    from app.services import classification
    from app.services.classification import StubClassificationModel

    study = Study(
        patient_id=patient.id, study_instance_uid="demo-cxr-1", modality="DX",
        study_date=datetime(2026, 9, 1), description="Рентгенография ОГК, прямая проекция (демо)",
        manufacturer="Philips", protocol="Chest PA", patient_age_years=6.0,
    )
    db.add(study)
    db.flush()
    series = Series(
        study_id=study.id, series_instance_uid="1.2.826.0.1.3680043.10.999.1.1", modality="DX",
        description="ОГК PA", instance_count=1, lossy_compressed=False,
        object_prefix="demo/demo-cxr-1/1.2.826.0.1.3680043.10.999.1.1",
    )
    db.add(series)
    db.flush()

    store = None
    if with_storage:  # pragma: no cover - нужны Orthanc и MinIO стенда
        from app.core.config import get_settings
        from app.services import storage
        from app.services.orthanc import clean_client

        dcm = synthetic_cxr_dicom("1.2.826.0.1.3680043.10.999.1", series.series_instance_uid,
                                  "1.2.826.0.1.3680043.10.999.1.1.1")
        client = clean_client()
        try:
            client.upload_dicom(dcm)
        finally:
            client.close()
        settings = get_settings()
        storage.ensure_buckets()
        storage.put_object(settings.bucket_images, f"{series.object_prefix}/demo.dcm", dcm)

        def store(key: str, data: bytes) -> str:
            return storage.put_object(settings.bucket_masks, key, data, content_type="image/png")

    drafts = 0
    for status, semver in ((ModelStatus.ACTIVE, "0.1.0"), (ModelStatus.SHADOW, "0.2.0")):
        mv = ModelVersion(
            name="demo_cxr_peds", semver=semver, weights_hash=f"demo-cxr-{semver}",
            applicability=PEDS_CXR_APPLICABILITY, status=status, task="classification",
            operating_points=DEMO_OPERATING_POINTS,
        )
        db.add(mv)
        db.flush()
        model = StubClassificationModel(sorted(DEMO_OPERATING_POINTS), mv.weights_hash)
        out = classification.classify_series(db, series=series, model_version=mv, model=model,
                                             store_artifact=store)
        if not out.shadow_run:
            drafts = len(out.finding_ids)
    return {"cxr_series_id": str(series.id), "cxr_drafts": drafts}


def seed(db: Session, *, with_storage: bool = False) -> dict:
    """Наполнить БД демо-данными. Идемпотентно по StudyInstanceUID."""
    # Режим установки — RESEARCH (не для клинического применения).
    if db.execute(select(OperatingModeState).where(OperatingModeState.modality == "*")).scalar_one_or_none() is None:
        db.add(OperatingModeState(modality="*"))
        db.flush()

    if db.execute(select(Study).where(Study.study_instance_uid == "demo-study-1")).scalar_one_or_none():
        return {"skipped": "already_seeded"}

    patient = Patient()
    db.add(patient)
    db.flush()
    db.add(PatientIdentifier(
        patient_id=patient.id, id_type="name_translit",
        normalized_value=identifier_value("name_translit", "Демо Пациент"),   # токен, не ФИО (SR-9)
    ))
    db.flush()

    mv = _active_model(db)
    model = StubSegmentationModel(
        [s.key for s in structures_for_region("CHEST")], weights_hash=mv.weights_hash
    )

    # Два исследования разных дат — для сравнения во времени.
    s1 = _study_with_series(db, patient, uid="demo-study-1", date=datetime(2026, 1, 15))
    s2 = _study_with_series(db, patient, uid="demo-study-2", date=datetime(2026, 6, 20))
    for series in (s1, s2):
        segmentation.segment_series(db, series=series, model_version=mv, model=model, age_years=45.0)

    # Отдельный обезличенный ребёнок — рентген ОГК для пилота NCMC.
    child = Patient()
    db.add(child)
    db.flush()
    cxr = _seed_pediatric_cxr(db, child, with_storage=with_storage)

    db.commit()
    return {"patient_id": str(patient.id), "studies": 3, **cxr}


def main() -> None:
    import sys

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        result = seed(db, with_storage="--with-storage" in sys.argv)
        print("Демо-данные:", result)
        print("Откройте рабочее место врача, войдите как radiologist и подтвердите находки.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
