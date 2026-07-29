"""Управление режимами работы (ТЗ, раздел 2). Смена — только администратор, с аудитом."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.modes import OperatingMode, can_transition
from app.core.roles import Role
from app.db.session import get_db
from app.models.audit import AuditAction, OperatingModeState
from app.services import audit

router = APIRouter(prefix="/modes", tags=["modes"])


class ModeOut(BaseModel):
    modality: str
    mode: OperatingMode


class ModeChangeIn(BaseModel):
    modality: str = "*"
    target_mode: OperatingMode


@router.get("", response_model=list[ModeOut])
def list_modes(db: Session = Depends(get_db)) -> list[ModeOut]:
    rows = db.execute(select(OperatingModeState)).scalars().all()
    return [ModeOut(modality=r.modality, mode=r.mode) for r in rows]


@router.post("", response_model=ModeOut)
def change_mode(
    payload: ModeChangeIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> ModeOut:
    """Сменить режим. Проверка допустимости перехода + запись в аудит (SR-8, раздел 2)."""
    state = db.execute(
        select(OperatingModeState).where(OperatingModeState.modality == payload.modality)
    ).scalar_one_or_none()

    current = state.mode if state else OperatingMode.RESEARCH
    if current != payload.target_mode and not can_transition(current, payload.target_mode):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Переход {current.value} → {payload.target_mode.value} запрещён. "
                "Новая модель/клиника обязана пройти SHADOW перед ASSIST (раздел 9)."
            ),
        )

    if state is None:
        state = OperatingModeState(modality=payload.modality, mode=payload.target_mode)
        db.add(state)
    else:
        state.mode = payload.target_mode
    state.changed_by = user.subject
    db.flush()

    audit.record(
        db,
        actor=user.subject,
        actor_role="admin",
        action=AuditAction.MODE_CHANGE,
        entity_type="operating_mode",
        entity_id=state.id,
        details={
            "modality": payload.modality,
            "from": current.value,
            "to": payload.target_mode.value,
        },
    )
    db.commit()
    return ModeOut(modality=state.modality, mode=state.mode)
