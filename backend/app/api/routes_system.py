"""Состояние системы для администратора и ИТ (SR-4): подробные проверки компонентов."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
def system_status(_: CurrentUser = Depends(require_roles(Role.ADMIN, Role.AUDITOR))) -> dict:
    from app.services.system_status import collect

    return collect()


@router.get("/data-inventory")
def data_inventory(_: CurrentUser = Depends(require_roles(Role.ADMIN, Role.AUDITOR))) -> dict:
    """Что хранится: записи и даты по категориям политики хранения (только агрегаты)."""
    from app.db.session import IdMapSessionLocal, SessionLocal
    from app.services.data_inventory import build_inventory

    with SessionLocal() as db, IdMapSessionLocal() as idmap:
        return build_inventory(db, idmap)
