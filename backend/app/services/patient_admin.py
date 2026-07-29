"""Объединение и разъединение записей пациентов (ТЗ, FR-1).

Решает проблему транслитерации кириллица/латиница: одно физическое лицо могло
попасть в систему под разными написаниями ФИО и номерами. Врач/администратор
объединяет такие записи; при ошибке — разъединяет. Вся история — в аудите (SR-8).

Инварианты:
- Объединение и разъединение — значимые действия, доступны admin/radiologist,
  каждое пишется в аудит с составом перенесённых сущностей.
- Записи пациентов не удаляются: слитый пациент остаётся «надгробием»
  (merged_into_id), что сохраняет историю и делает операцию обратимой.
- Идентифицирующие данные (ФИО) остаются в идентифицирующем контуре; здесь
  переносятся только внутренние связи (SR-9).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditAction
from app.models.imaging import Study
from app.models.patient import Patient, PatientIdentifier
from app.services import audit


class MergeError(Exception):
    """Недопустимая операция объединения/разъединения."""


@dataclass
class MergeOutcome:
    target_id: uuid.UUID
    moved_studies: int
    moved_identifiers: int


def merge_patients(
    db: Session, *, source_id: uuid.UUID, target_id: uuid.UUID, actor: str
) -> MergeOutcome:
    """Объединить source в target: перенести исследования и идентификаторы.

    source остаётся надгробием (merged_into_id=target). Идентификаторам
    проставляется merged_into=source_id как провенанс (для последующего split).
    """
    if source_id == target_id:
        raise MergeError("Нельзя объединить пациента с самим собой")
    source = db.get(Patient, source_id)
    target = db.get(Patient, target_id)
    if source is None or target is None:
        raise MergeError("Пациент-источник или пациент-приёмник не найден")
    if source.is_merged:
        raise MergeError("Источник уже объединён в другую запись")
    if target.is_merged:
        raise MergeError("Приёмник сам является объединённой записью")

    studies = db.execute(select(Study).where(Study.patient_id == source_id)).scalars().all()
    for st in studies:
        st.patient_id = target_id

    identifiers = db.execute(
        select(PatientIdentifier).where(PatientIdentifier.patient_id == source_id)
    ).scalars().all()
    for ident in identifiers:
        ident.patient_id = target_id
        ident.merged_into = source_id  # провенанс: откуда пришёл идентификатор

    source.merged_into_id = target_id
    db.flush()

    audit.record(
        db,
        actor=actor,
        action=AuditAction.PATIENT_ACCESS,
        entity_type="patient",
        entity_id=target_id,
        details={
            "event": "merge",
            "source": str(source_id),
            "target": str(target_id),
            "moved_studies": len(studies),
            "moved_identifiers": len(identifiers),
        },
    )
    return MergeOutcome(target_id, len(studies), len(identifiers))


@dataclass
class SplitOutcome:
    new_patient_id: uuid.UUID
    moved_studies: int
    moved_identifiers: int


def split_patient(
    db: Session,
    *,
    source_patient_id: uuid.UUID,
    identifier_ids: list[uuid.UUID],
    study_ids: list[uuid.UUID] | None = None,
    actor: str,
) -> SplitOutcome:
    """Выделить из пациента новую запись с указанными идентификаторами и исследованиями.

    Используется, когда две разные персоны были ошибочно объединены. Создаёт нового
    активного пациента и переносит на него выбранные сущности. Если ранее пациент был
    надгробием этого источника — снимает провенанс merged_into.
    """
    source = db.get(Patient, source_patient_id)
    if source is None:
        raise MergeError("Пациент не найден")
    if not identifier_ids and not study_ids:
        raise MergeError("Не указано, что выделять (идентификаторы/исследования)")

    new_patient = Patient()
    db.add(new_patient)
    db.flush()

    moved_ident = 0
    for ident_id in identifier_ids:
        ident = db.get(PatientIdentifier, ident_id)
        if ident is None or ident.patient_id != source_patient_id:
            raise MergeError(f"Идентификатор {ident_id} не принадлежит пациенту")
        ident.patient_id = new_patient.id
        ident.merged_into = None
        moved_ident += 1

    moved_studies = 0
    for study_id in (study_ids or []):
        st = db.get(Study, study_id)
        if st is None or st.patient_id != source_patient_id:
            raise MergeError(f"Исследование {study_id} не принадлежит пациенту")
        st.patient_id = new_patient.id
        moved_studies += 1

    db.flush()
    audit.record(
        db,
        actor=actor,
        action=AuditAction.PATIENT_ACCESS,
        entity_type="patient",
        entity_id=new_patient.id,
        details={
            "event": "split",
            "from": str(source_patient_id),
            "new_patient": str(new_patient.id),
            "moved_identifiers": moved_ident,
            "moved_studies": moved_studies,
        },
    )
    return SplitOutcome(new_patient.id, moved_studies, moved_ident)
