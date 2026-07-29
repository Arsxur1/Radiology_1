"""Совмещение модальностей (ТЗ, FR-4). Запуск, просмотр, визуальная проверка врачом."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.imaging import Series
from app.models.registration import Registration, RegistrationStage
from app.services import registration
from app.services.registration import RegistrationError, StubRegistrationEngine

router = APIRouter(prefix="/registration", tags=["registration"])


class RunIn(BaseModel):
    fixed_series_id: uuid.UUID
    moving_series_id: uuid.UUID
    up_to_stage: RegistrationStage = RegistrationStage.DEFORMABLE
    use_stub: bool = True


class ReviewIn(BaseModel):
    approved: bool


class RegistrationOut(BaseModel):
    id: uuid.UUID
    fixed_series_id: uuid.UUID
    moving_series_id: uuid.UUID
    stage: str
    metric_name: str
    metric_value: float | None
    quality: dict
    review_status: str
    usable_for_measurements: bool


def _out(r: Registration) -> RegistrationOut:
    return RegistrationOut(
        id=r.id, fixed_series_id=r.fixed_series_id, moving_series_id=r.moving_series_id,
        stage=r.stage.value, metric_name=r.metric_name, metric_value=r.metric_value,
        quality=r.quality, review_status=r.review_status.value,
        usable_for_measurements=r.usable_for_measurements(),
    )


@router.post("", response_model=RegistrationOut)
def run(
    payload: RunIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RESEARCHER, Role.RADIOLOGIST)),
) -> RegistrationOut:
    """Совместить две серии (жёсткая→аффинная→деформируемая). Результат — на проверку."""
    fixed = db.get(Series, payload.fixed_series_id)
    moving = db.get(Series, payload.moving_series_id)
    if fixed is None or moving is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")

    if payload.use_stub:
        engine = StubRegistrationEngine()
    else:  # pragma: no cover
        from app.services.registration_engines import ItkRegistrationEngine

        engine = ItkRegistrationEngine()

    try:
        reg = registration.run_registration(
            db, fixed_series=fixed, moving_series=moving, engine=engine,
            up_to_stage=payload.up_to_stage, actor=user.subject,
        )
        db.commit()
    except RegistrationError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(reg)


@router.get("/{registration_id}", response_model=RegistrationOut)
def get_registration(registration_id: uuid.UUID, db: Session = Depends(get_db)) -> RegistrationOut:
    reg = db.get(Registration, registration_id)
    if reg is None:
        raise HTTPException(status_code=404, detail="Совмещение не найдено")
    return _out(reg)


@router.post("/{registration_id}/review", response_model=RegistrationOut)
def review(
    registration_id: uuid.UUID,
    payload: ReviewIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> RegistrationOut:
    """Визуальная проверка врачом (FR-4): подтвердить или отклонить совмещение."""
    try:
        reg = registration.review_registration(
            db, registration_id=registration_id, approved=payload.approved, physician=user.subject,
        )
        db.commit()
    except RegistrationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _out(reg)
