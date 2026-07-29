"""Чтение аудит-лога (ТЗ, FR-12: роль аудитора — только чтение)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.audit import AuditLog
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor: str
    action: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    details: dict


@router.get("", response_model=list[AuditOut])
def list_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.AUDITOR, Role.ADMIN)),
) -> list[AuditOut]:
    rows = (
        db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return [
        AuditOut(
            id=r.id,
            created_at=r.created_at,
            actor=r.actor,
            action=r.action.value,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            details=r.details,
        )
        for r in rows
    ]


@router.get("/verify")
def verify_audit(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.AUDITOR, Role.ADMIN)),
) -> dict:
    """Проверка целостности хеш-цепочки (критерий приёмки, раздел 10)."""
    return {"intact": audit.verify_chain(db)}
