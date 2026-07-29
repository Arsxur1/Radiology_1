"""Оркестрация приёма (ТЗ, FR-1).

Шаги: чтение DICOM → обезличивание → запись map в идентифицирующий контур →
зеркалирование study/series в PostgreSQL → загрузка обезличенного объекта в
clean-Orthanc/MinIO → аудит. Детект дубликатов по обезличенному SOPInstanceUID.

На этапе 1 не подключаются модели: только приём/хранение/зеркалирование.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditAction
from app.models.idmap import PatientPseudonymMap
from app.models.imaging import Series, Study
from app.models.patient import Patient, PatientIdentifier
from app.services import audit
from app.services.anonymization import DeidResult
from app.services.patient_matching import match_patient, normalize_identifier


@dataclass
class IngestOutcome:
    study_id: uuid.UUID
    series_id: uuid.UUID
    patient_id: uuid.UUID
    created_study: bool
    created_series: bool
    duplicate: bool
    needs_manual_link: bool


def _get_or_create_patient(
    db: Session, *, plan: DeidResult
) -> tuple[Patient, bool]:
    """Найти/создать пациента. Возвращает (пациент, требуется_ручная_привязка)."""
    if plan.real_mrn:
        result = match_patient(db, id_type="mrn", raw_value=plan.real_mrn)
        if result.needs_manual_confirmation:
            # Неоднозначность — создаём нового пациента, помечаем к ручной привязке.
            patient = Patient()
            db.add(patient)
            db.flush()
            return patient, True
        if result.patient is not None:
            return result.patient, False

    patient = Patient()
    db.add(patient)
    db.flush()
    if plan.real_mrn:
        db.add(
            PatientIdentifier(
                patient_id=patient.id,
                id_type="mrn",
                normalized_value=normalize_identifier(plan.real_mrn),
                issuer=None,
            )
        )
    if plan.real_name:
        db.add(
            PatientIdentifier(
                patient_id=patient.id,
                id_type="name_translit",
                normalized_value=normalize_identifier(plan.real_name),
            )
        )
    db.flush()
    return patient, False


def persist_ingest(
    db: Session,
    idmap_db: Session,
    *,
    plan: DeidResult,
    study_meta: dict,
    series_meta: dict,
    actor: str = "system:ingest",
) -> IngestOutcome:
    """Зеркалировать один обезличенный объект в модель данных.

    study_meta / series_meta — уже обезличенные метаданные (модальность, аппарат,
    толщина среза и т.д.). Идентифицирующие поля берутся из plan и пишутся ТОЛЬКО
    в идентифицирующий контур.
    """
    pseudo_study_uid = plan.pseudonym_study_uid or study_meta["study_instance_uid"]

    # Детект дубликата по обезличенному SeriesInstanceUID.
    existing_series = db.execute(
        select(Series).where(
            Series.series_instance_uid == series_meta["series_instance_uid"]
        )
    ).scalar_one_or_none()
    if existing_series is not None:
        return IngestOutcome(
            study_id=existing_series.study_id,
            series_id=existing_series.id,
            patient_id=_study_patient_id(db, existing_series.study_id),
            created_study=False,
            created_series=False,
            duplicate=True,
            needs_manual_link=False,
        )

    patient, needs_manual = _get_or_create_patient(db, plan=plan)

    # Study.
    study = db.execute(
        select(Study).where(Study.study_instance_uid == pseudo_study_uid)
    ).scalar_one_or_none()
    created_study = False
    if study is None:
        study = Study(
            patient_id=patient.id,
            study_instance_uid=pseudo_study_uid,
            modality=study_meta.get("modality", "OT"),
            study_date=study_meta.get("study_date"),
            description=study_meta.get("description"),
            manufacturer=study_meta.get("manufacturer"),
            manufacturer_model=study_meta.get("manufacturer_model"),
            software_version=study_meta.get("software_version"),
            protocol=study_meta.get("protocol"),
            orthanc_study_id=study_meta.get("orthanc_study_id"),
        )
        db.add(study)
        db.flush()
        created_study = True

    # Series.
    series = Series(
        study_id=study.id,
        series_instance_uid=series_meta["series_instance_uid"],
        series_number=series_meta.get("series_number"),
        modality=series_meta.get("modality", study.modality),
        description=series_meta.get("description"),
        instance_count=series_meta.get("instance_count"),
        slice_thickness_mm=series_meta.get("slice_thickness_mm"),
        voxel_spacing=series_meta.get("voxel_spacing"),
        transfer_syntax=series_meta.get("transfer_syntax"),
        lossy_compressed=series_meta.get("lossy_compressed", False),
        contrast_agent=series_meta.get("contrast_agent"),
        orthanc_series_id=series_meta.get("orthanc_series_id"),
        object_prefix=series_meta.get("object_prefix"),
    )
    db.add(series)
    db.flush()

    # Идентифицирующий контур: соответствие псевдоним ↔ реальные данные (SR-9).
    idmap_db.add(
        PatientPseudonymMap(
            pseudonym_patient_id=patient.id,
            real_mrn=plan.real_mrn,
            real_name=plan.real_name,
            real_study_instance_uid=plan.real_study_uid,
            pseudonym_study_instance_uid=pseudo_study_uid,
        )
    )
    idmap_db.commit()

    # Аудит (SR-5, раздел 5): приём и факт обезличивания.
    audit.record(
        db,
        actor=actor,
        action=AuditAction.STUDY_INGEST,
        entity_type="series",
        entity_id=series.id,
        details={
            "study_instance_uid": pseudo_study_uid,
            "modality": series.modality,
            "removed_tags": plan.removed_tags,
            "needs_manual_link": needs_manual,
        },
    )

    return IngestOutcome(
        study_id=study.id,
        series_id=series.id,
        patient_id=patient.id,
        created_study=created_study,
        created_series=True,
        duplicate=False,
        needs_manual_link=needs_manual,
    )


def _study_patient_id(db: Session, study_id: uuid.UUID) -> uuid.UUID:
    study = db.get(Study, study_id)
    return study.patient_id if study else study_id
