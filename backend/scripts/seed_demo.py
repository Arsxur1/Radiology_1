"""Демо-данные для показа системы без PACS и GPU (режим RESEARCH).

Создаёт обезличенного пациента, два КТ-исследования грудной клетки с сериями,
активную модель-заглушку и прогоняет сегментацию — так во фронтенде сразу видны
worklist, находки (черновик ИИ), сборка заключения и динамика во времени.

Запуск на стенде:
    docker compose exec backend python scripts/seed_demo.py

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
from app.services.patient_matching import normalize_identifier
from app.services.structure_catalog import structures_for_region

CHEST_APPLICABILITY = {
    "modality": ["CT"],
    "body_part": ["CHEST"],
    "slice_thickness_mm": {"max": 3.0},
    "age": {"min_years": 18},
    "manufacturers": ["Siemens", "GE", "Philips", "Canon"],
    "allow_lossy": False,
}


def _active_model(db: Session) -> ModelVersion:
    mv = db.execute(
        select(ModelVersion).where(ModelVersion.status == ModelStatus.ACTIVE)
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


def seed(db: Session) -> dict:
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
        normalized_value=normalize_identifier("Демо Пациент"),
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

    db.commit()
    return {"patient_id": str(patient.id), "studies": 2}


def main() -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        result = seed(db)
        print("Демо-данные:", result)
        print("Откройте рабочее место врача, войдите как radiologist и подтвердите находки.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
