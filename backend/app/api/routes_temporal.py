"""Сравнение находок во времени (ТЗ, FR-7). Без ИИ, обязательно в первой версии."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.services import temporal_repo

router = APIRouter(prefix="/temporal", tags=["temporal"])


class DeltaOut(BaseModel):
    metric: str
    previous: float
    current: float
    absolute: float
    percent: float | None
    direction: str


class PointOut(BaseModel):
    study_id: str
    study_date: str | None
    finding_id: str
    measurements: dict


class SeriesOut(BaseModel):
    key: str
    label: str | None
    points: list[PointOut]
    deltas: list[DeltaOut]


@router.get("/patient/{patient_id}", response_model=list[SeriesOut])
def patient_dynamics(
    patient_id: uuid.UUID,
    confirmed_only: bool = True,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.RADIOLOGIST, Role.CLINICIAN, Role.ADMIN)),
) -> list[SeriesOut]:
    """Динамика подтверждённых находок пациента по времени (FR-7)."""
    series = temporal_repo.patient_series(db, patient_id=patient_id, confirmed_only=confirmed_only)
    out: list[SeriesOut] = []
    for s in series:
        out.append(
            SeriesOut(
                key=s.key,
                label=s.label,
                points=[
                    PointOut(
                        study_id=p.study_id,
                        study_date=p.study_date.isoformat() if p.study_date else None,
                        finding_id=p.finding_id,
                        measurements=p.measurements,
                    )
                    for p in s.points
                ],
                deltas=[
                    DeltaOut(
                        metric=d.metric, previous=d.previous, current=d.current,
                        absolute=d.absolute, percent=d.percent, direction=d.direction,
                    )
                    for d in s.deltas.values()
                ],
            )
        )
    return out
