"""Находки и правки врача (ТЗ, FR-9, SR-2, SR-6).

Каждое действие — отдельный явный вызов по одной находке. Нет «принять всё»
и авто-принятия (SR-2). Каждое решение порождает correction (обучающий сигнал).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.imaging import Series
from app.models.ml import Finding, FindingSource
from app.services import corrections
from app.services.corrections import CorrectionError
from app.services.mode_state import model_results_visible

router = APIRouter(prefix="/findings", tags=["findings"])


class FindingOut(BaseModel):
    id: uuid.UUID
    series_id: uuid.UUID
    coding_system: str
    code: str | None
    label: str | None
    measurements: dict
    source: str
    confirmation_status: str


class ConfirmIn(BaseModel):
    time_spent_seconds: float | None = None


class ModifyIn(BaseModel):
    measurements: dict | None = None
    code: str | None = None
    label: str | None = None
    coordinates: dict | None = None
    time_spent_seconds: float | None = None


class RejectIn(BaseModel):
    reason: str | None = None
    time_spent_seconds: float | None = None


class CreateFindingIn(BaseModel):
    series_id: uuid.UUID
    measurements: dict
    code: str | None = None
    label: str | None = None
    coordinates: dict | None = None
    coding_system: str = "RadLex"
    time_spent_seconds: float | None = None


def _out(f: Finding) -> FindingOut:
    return FindingOut(
        id=f.id,
        series_id=f.series_id,
        coding_system=f.coding_system,
        code=f.code,
        label=f.label,
        measurements=f.measurements,
        source=f.source.value,
        confirmation_status=f.confirmation_status.value,
    )


@router.get("/series/{series_id}", response_model=list[FindingOut])
def list_series_findings(series_id: uuid.UUID, db: Session = Depends(get_db)) -> list[FindingOut]:
    """Находки серии. В режиме SHADOW результаты модели не показываются (раздел 2);
    находки самого врача видны всегда."""
    rows = db.execute(select(Finding).where(Finding.series_id == series_id)).scalars().all()
    series = db.get(Series, series_id)
    modality = series.modality if series else None
    if not model_results_visible(db, modality):
        rows = [f for f in rows if f.source != FindingSource.MODEL]
    return [_out(f) for f in rows]


@router.post("/{finding_id}/confirm", response_model=FindingOut)
def confirm(
    finding_id: uuid.UUID,
    payload: ConfirmIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> FindingOut:
    try:
        corrections.confirm_finding(
            db, finding_id=finding_id, physician=user.subject,
            time_spent_seconds=payload.time_spent_seconds,
        )
        db.commit()
    except CorrectionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db.get(Finding, finding_id))


@router.post("/{finding_id}/modify", response_model=FindingOut)
def modify(
    finding_id: uuid.UUID,
    payload: ModifyIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> FindingOut:
    try:
        corrections.modify_finding(
            db, finding_id=finding_id, physician=user.subject,
            new_measurements=payload.measurements, new_code=payload.code,
            new_label=payload.label, new_coordinates=payload.coordinates,
            time_spent_seconds=payload.time_spent_seconds,
        )
        db.commit()
    except CorrectionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db.get(Finding, finding_id))


@router.post("/{finding_id}/reject", response_model=FindingOut)
def reject(
    finding_id: uuid.UUID,
    payload: RejectIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> FindingOut:
    try:
        corrections.reject_finding(
            db, finding_id=finding_id, physician=user.subject,
            reason=payload.reason, time_spent_seconds=payload.time_spent_seconds,
        )
        db.commit()
    except CorrectionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db.get(Finding, finding_id))


@router.post("", response_model=FindingOut)
def create(
    payload: CreateFindingIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> FindingOut:
    """Врач добавляет находку, пропущенную моделью (обучающий сигнал)."""
    finding = corrections.create_physician_finding(
        db, series_id=payload.series_id, physician=user.subject,
        measurements=payload.measurements, code=payload.code, label=payload.label,
        coordinates=payload.coordinates, coding_system=payload.coding_system,
        time_spent_seconds=payload.time_spent_seconds,
    )
    db.commit()
    return _out(finding)
