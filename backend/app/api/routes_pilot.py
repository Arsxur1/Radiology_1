"""Сводная панель пилота: только агрегаты, без идентификаторов пациентов."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.services.pilot_dashboard import build_dashboard

router = APIRouter(prefix="/pilot", tags=["pilot"])


@router.get("/dashboard")
def dashboard(
    weeks: int = Query(12, ge=1, le=52),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN, Role.AUDITOR)),
) -> dict:
    return build_dashboard(db, weeks=weeks)
