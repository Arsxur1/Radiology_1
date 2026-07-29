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
from app.models.patient import Patient, PatientIdentifier
from app.services import patient_admin
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
    )


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: uuid.UUID, db: Session = Depends(get_db)) -> PatientOut:
    p = db.get(Patient, patient_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Пациент не найден")
    return _out(db, p)


@router.get("/search/by-identifier", response_model=list[PatientOut])
def search_by_identifier(
    value: str,
    db: Session = Depends(get_db),
) -> list[PatientOut]:
    """Поиск по нормализованному идентификатору (транслитерация уже применена клиентом
    ingest). Возвращает кандидатов для ручного объединения при неоднозначности."""
    from app.services.patient_matching import normalize_identifier

    norm = normalize_identifier(value)
    idents = db.execute(
        select(PatientIdentifier).where(PatientIdentifier.normalized_value == norm)
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
