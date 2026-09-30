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
