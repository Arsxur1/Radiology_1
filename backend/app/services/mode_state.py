"""Определение текущего режима работы по модальности (ТЗ, раздел 2)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.modes import OperatingMode, results_visible_to_physician
from app.models.audit import OperatingModeState


def current_mode(db: Session, modality: str | None) -> OperatingMode:
    """Актуальный режим для модальности; при отсутствии — правило '*'; иначе дефолт."""
    state = None
    if modality:
        state = db.execute(
            select(OperatingModeState).where(OperatingModeState.modality == modality)
        ).scalar_one_or_none()
    if state is None:
        state = db.execute(
            select(OperatingModeState).where(OperatingModeState.modality == "*")
        ).scalar_one_or_none()
    if state is not None:
        return state.mode
    return OperatingMode(get_settings().default_operating_mode)


def model_results_visible(db: Session, modality: str | None) -> bool:
    """Показывать ли результаты модели врачу в текущем режиме (SHADOW → нет)."""
    return results_visible_to_physician(current_mode(db, modality))
