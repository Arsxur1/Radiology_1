"""Просмотр исследований и серий (обезличенные данные)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.imaging import Study

router = APIRouter(prefix="/studies", tags=["studies"])


class SeriesOut(BaseModel):
    id: uuid.UUID
    series_instance_uid: str
    modality: str
    description: str | None
    instance_count: int | None
    slice_thickness_mm: float | None
    lossy_compressed: bool
    is_3d_capable: bool


class StudyOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    study_instance_uid: str
    modality: str
    description: str | None
    manufacturer: str | None
    series: list[SeriesOut]


@router.get("", response_model=list[StudyOut])
def list_studies(
    modality: str | None = None,
    patient_id: uuid.UUID | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[StudyOut]:
    stmt = select(Study).order_by(Study.study_date.desc().nullslast()).limit(limit)
    if modality:
        stmt = stmt.where(Study.modality == modality)
    if patient_id:
        stmt = stmt.where(Study.patient_id == patient_id)
    studies = db.execute(stmt).scalars().all()
    return [_to_study_out(s) for s in studies]


@router.get("/{study_id}", response_model=StudyOut)
def get_study(study_id: uuid.UUID, db: Session = Depends(get_db)) -> StudyOut:
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Исследование не найдено")
    return _to_study_out(study)


def _to_study_out(study: Study) -> StudyOut:
    return StudyOut(
        id=study.id,
        patient_id=study.patient_id,
        study_instance_uid=study.study_instance_uid,
        modality=study.modality,
        description=study.description,
        manufacturer=study.manufacturer,
        series=[
            SeriesOut(
                id=s.id,
                series_instance_uid=s.series_instance_uid,
                modality=s.modality,
                description=s.description,
                instance_count=s.instance_count,
                slice_thickness_mm=s.slice_thickness_mm,
                lossy_compressed=s.lossy_compressed,
                is_3d_capable=s.is_3d_capable(),
            )
            for s in study.series
        ],
    )
