"""Пациенты: просмотр, объединение и разъединение записей (ТЗ, FR-1, FR-12)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.audit import AuditAction
from app.models.patient import Patient, PatientIdentifier
from app.services import audit, patient_admin
from app.services.patient_admin import MergeError

router = APIRouter(prefix="/patients", tags=["patients"])


class IdentifierOut(BaseModel):
    id: uuid.UUID
    id_type: str
    normalized_value: str
    issuer: str | None
    active: bool


class PatientOut(BaseModel):
    id: uuid.UUID
    merged_into_id: uuid.UUID | None
    is_merged: bool
    identifiers: list[IdentifierOut]
    study_count: int
    # Ждёт ручного сопоставления (неоднозначный номер карты при приёме).
    link_review: bool = False
    # Отзыв согласия: исследования не идут в обучение и калибровку.
    training_excluded: bool = False


class TrainingExclusionIn(BaseModel):
    excluded: bool
    basis: str          # код из GET /patients/training-exclusion-bases


class LinkReviewOut(BaseModel):
    patient: PatientOut
    candidates: list[PatientOut]


class MergeIn(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID


class SplitIn(BaseModel):
    source_patient_id: uuid.UUID
    identifier_ids: list[uuid.UUID] = []
    study_ids: list[uuid.UUID] = []


def _out(db: Session, p: Patient) -> PatientOut:
    idents = db.execute(
        select(PatientIdentifier).where(PatientIdentifier.patient_id == p.id)
    ).scalars().all()
    return PatientOut(
        id=p.id,
        merged_into_id=p.merged_into_id,
        is_merged=p.is_merged,
        identifiers=[
            IdentifierOut(
                id=i.id, id_type=i.id_type, normalized_value=i.normalized_value,
                issuer=i.issuer, active=i.active,
            )
            for i in idents
        ],
        study_count=len(p.studies),
        link_review=p.link_review,
        training_excluded=p.training_excluded,
    )


@router.get("/training-exclusion-bases")
def training_exclusion_bases(
    _: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> list[dict]:
    return [{"code": k, "label": v} for k, v in patient_admin.TRAINING_EXCLUSION_BASES.items()]


@router.post("/{patient_id}/training-exclusion", response_model=PatientOut)
def training_exclusion(
    patient_id: uuid.UUID,
    payload: TrainingExclusionIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> PatientOut:
    """Отзыв согласия на использование данных для обучения (или снятие), с аудитом."""
    try:
        p = patient_admin.set_training_exclusion(db, patient_id=patient_id, excluded=payload.excluded,
                                                 actor=user.subject, basis=payload.basis)
        db.commit()
    except MergeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db, p)


@router.get("/link-review", response_model=list[LinkReviewOut])
def link_review(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RADIOLOGIST)),
) -> list[LinkReviewOut]:
    """Записи, ждущие ручного сопоставления, с кандидатами (только внутренние UUID и отпечатки)."""
    audit.record_access(db, user, AuditAction.PATIENT_ACCESS, entity_type="patient_link_review",
                        details={"what": "очередь сопоставления пациентов"})
    out = []
    for p in patient_admin.link_review_queue(db):
        cands = [db.get(Patient, uuid.UUID(c)) for c in (p.link_candidates or [])]
        # Кандидат мог быть объединён позже — показываем действующую запись.
        resolved = {}
        for c in cands:
            while c is not None and c.merged_into_id is not None:
                c = db.get(Patient, c.merged_into_id)
            if c is not None and c.id != p.id:
                resolved[c.id] = c
        out.append(LinkReviewOut(patient=_out(db, p), candidates=[_out(db, c) for c in resolved.values()]))
    return out


@router.post("/{patient_id}/keep-separate", response_model=PatientOut)
def keep_separate(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RADIOLOGIST)),
) -> PatientOut:
    """Сопоставление разобрано: это отдельный пациент."""
    try:
        p = patient_admin.keep_separate(db, patient_id=patient_id, actor=user.subject)
        db.commit()
    except MergeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db, p)


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RADIOLOGIST)),
) -> PatientOut:
    p = db.get(Patient, patient_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Пациент не найден")
    audit.record_access(db, user, AuditAction.PATIENT_ACCESS, entity_type="patient", entity_id=p.id,
                        details={"what": "карточка пациента"})
    return _out(db, p)


@router.get("/search/by-identifier", response_model=list[PatientOut])
def search_by_identifier(
    value: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RADIOLOGIST)),
) -> list[PatientOut]:
    # Значение идентификатора в журнал не пишем (может быть ФИО) — только факт поиска.
    audit.record_access(db, user, AuditAction.PATIENT_ACCESS, entity_type="patient_search",
                        details={"what": "поиск пациента по идентификатору"})
    """Поиск по номеру карты или ФИО (нормализация и транслитерация — как при приёме).

    В доверенном контуре хранятся только ключевые токены (SR-9): введённое значение
    превращается в токен и сравнивается с ними. Возвращает кандидатов для объединения.
    """
    from app.services.patient_matching import identifier_value

    tokens = [identifier_value(t, value) for t in ("mrn", "name_translit")]
    idents = db.execute(
        select(PatientIdentifier).where(PatientIdentifier.normalized_value.in_(tokens))
    ).scalars().all()
    seen: dict[uuid.UUID, Patient] = {}
    for i in idents:
        p = db.get(Patient, i.patient_id)
        if p is not None:
            seen[p.id] = p
    return [_out(db, p) for p in seen.values()]


@router.post("/merge", response_model=PatientOut)
def merge(
    payload: MergeIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RADIOLOGIST)),
) -> PatientOut:
    """Объединить две записи одного пациента (FR-1)."""
    try:
        outcome = patient_admin.merge_patients(
            db, source_id=payload.source_id, target_id=payload.target_id, actor=user.subject
        )
        db.commit()
    except MergeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db, db.get(Patient, outcome.target_id))


@router.post("/split", response_model=PatientOut)
def split(
    payload: SplitIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RADIOLOGIST)),
) -> PatientOut:
    """Разъединить ошибочно объединённые записи, выделив новую (FR-1)."""
    try:
        outcome = patient_admin.split_patient(
            db,
            source_patient_id=payload.source_patient_id,
            identifier_ids=payload.identifier_ids,
            study_ids=payload.study_ids,
            actor=user.subject,
        )
        db.commit()
    except MergeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db, db.get(Patient, outcome.new_patient_id))
