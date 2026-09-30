"""Совмещение модальностей (ТЗ, FR-4). Запуск, просмотр, визуальная проверка врачом."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.imaging import Series
from app.models.registration import Registration, RegistrationStage
from app.services import registration
from app.services.registration import RegistrationBlocked, RegistrationError, StubRegistrationEngine

router = APIRouter(prefix="/registration", tags=["registration"])


class RunIn(BaseModel):
    fixed_series_id: uuid.UUID
    moving_series_id: uuid.UUID
    up_to_stage: RegistrationStage = RegistrationStage.DEFORMABLE
    # Заглушка — только для демонстрации: её результат подтвердить нельзя.
    use_stub: bool = False


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
    # Почему подтвердить нельзя (не посчитано, заглушка, «складки»); пусто — можно.
    review_blockers: list[str] = []
    has_preview: bool = False


def _out(r: Registration) -> RegistrationOut:
    return RegistrationOut(
        id=r.id, fixed_series_id=r.fixed_series_id, moving_series_id=r.moving_series_id,
        stage=r.stage.value, metric_name=r.metric_name, metric_value=r.metric_value,
        quality={k: v for k, v in (r.quality or {}).items() if k != "preview_ref"},
        review_status=r.review_status.value,
        usable_for_measurements=r.usable_for_measurements(),
        review_blockers=registration.review_blockers(r),
        has_preview=bool((r.quality or {}).get("preview_ref")),
    )


def enqueue_registration(registration_id: uuid.UUID, actor: str) -> None:
    from app.workers.celery_app import celery_app

    celery_app.send_task("registration.run", args=[str(registration_id), actor])


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

    try:
        if payload.use_stub:
            reg = registration.run_registration(
                db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine(),
                up_to_stage=payload.up_to_stage, actor=user.subject,
            )
        else:
            reg = registration.queue_registration(
                db, fixed_series=fixed, moving_series=moving, up_to_stage=payload.up_to_stage,
                actor=user.subject,
            )
        db.commit()
    except RegistrationError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not payload.use_stub:
        enqueue_registration(reg.id, user.subject)
    return _out(reg)


@router.get("", response_model=list[RegistrationOut])
def list_registrations(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RESEARCHER, Role.RADIOLOGIST)),
) -> list[RegistrationOut]:
    """Совмещения пациента, новые сверху — чтобы вернуться к проверке или публикации."""
    from sqlalchemy import select

    from app.models.imaging import Study

    rows = db.execute(
        select(Registration)
        .join(Series, Registration.fixed_series_id == Series.id)
        .join(Study, Series.study_id == Study.id)
        .where(Study.patient_id == patient_id)
        .order_by(Registration.created_at.desc())
    ).scalars().all()
    return [_out(r) for r in rows]


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
    except RegistrationBlocked as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except RegistrationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _out(reg)


@router.get("/{registration_id}/preview")
def preview(
    registration_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RESEARCHER, Role.RADIOLOGIST)),
) -> Response:
    """Шахматка «опорная | совмещённая» по трём центральным срезам — для визуальной проверки."""
    from app.services import storage

    reg = db.get(Registration, registration_id)
    ref = (reg.quality or {}).get("preview_ref") if reg else None
    if not ref:
        raise HTTPException(status_code=404, detail="Превью нет")
    return Response(content=storage.get_object_ref(ref), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


def enqueue_publish(registration_id: uuid.UUID) -> None:
    from app.workers.celery_app import celery_app

    celery_app.send_task("registration.publish", args=[str(registration_id)])


@router.post("/{registration_id}/publish", response_model=RegistrationOut)
def publish(
    registration_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> RegistrationOut:
    """Показать совмещённую серию в просмотрщике. Только после подтверждения качества врачом."""
    from app.models.registration import RegistrationReview

    reg = db.get(Registration, registration_id)
    if reg is None:
        raise HTTPException(status_code=404, detail="Совмещение не найдено")
    if reg.review_status != RegistrationReview.APPROVED:
        raise HTTPException(status_code=409, detail="Публикуется только совмещение, подтверждённое врачом")
    if not reg.transform_ref:
        raise HTTPException(status_code=409, detail="Нет сохранённого преобразования (демо-заглушка)")
    reg.quality = {**(reg.quality or {}), "published": {"status": "queued"}}
    db.commit()
    enqueue_publish(reg.id)
    return _out(reg)
