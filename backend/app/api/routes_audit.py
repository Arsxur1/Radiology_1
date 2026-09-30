"""Чтение аудит-лога (ТЗ, FR-12: роль аудитора — только чтение)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.audit import AuditAction, AuditLog
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    id: uuid.UUID
    seq: int | None
    created_at: datetime
    actor: str
    actor_role: str | None
    action: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    details: dict


READERS = require_roles(Role.AUDITOR, Role.ADMIN)


def _query(actor, action, entity_type, since, until, before_seq):
    q = select(AuditLog)
    if actor:
        q = q.where(AuditLog.actor.ilike(f"%{actor}%"))
    if action:
        q = q.where(AuditLog.action == AuditAction(action))
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at < until)
    if before_seq:
        q = q.where(AuditLog.seq < before_seq)
    return q.order_by(AuditLog.seq.desc())


def _out(r: AuditLog) -> AuditOut:
    return AuditOut(id=r.id, seq=r.seq, created_at=r.created_at, actor=r.actor, actor_role=r.actor_role,
                    action=r.action.value, entity_type=r.entity_type, entity_id=r.entity_id, details=r.details)


@router.get("", response_model=list[AuditOut])
def list_audit(
    limit: int = Query(100, ge=1, le=1000),
    actor: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_seq: int | None = Query(None, description="постранично: записи с номером меньше"),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(READERS),
) -> list[AuditOut]:
    rows = db.execute(_query(actor, action, entity_type, since, until, before_seq).limit(limit)).scalars().all()
    return [_out(r) for r in rows]


@router.get("/actions")
def audit_actions(_: CurrentUser = Depends(READERS)) -> list[str]:
    return [a.value for a in AuditAction]


@router.get("/export.csv")
def export_csv(
    actor: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(READERS),
) -> Response:
    """Выгрузка журнала по фильтру (для проверок). Сама выгрузка тоже журналируется."""
    import csv
    import io
    import json

    rows = db.execute(_query(actor, action, entity_type, since, until, None).limit(100_000)).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["seq", "time_utc", "actor", "roles", "action", "entity_type", "entity_id", "details", "entry_hash"])
    for r in rows:
        w.writerow([r.seq, r.created_at.isoformat(), r.actor, r.actor_role or "", r.action.value,
                    r.entity_type or "", r.entity_id or "", json.dumps(r.details, ensure_ascii=False), r.entry_hash])
    audit.record_access(db, user, AuditAction.EXPORT, entity_type="audit_log",
                        details={"what": "выгрузка журнала аудита", "rows": len(rows),
                                 "filter": {"actor": actor, "action": action, "entity_type": entity_type,
                                            "since": str(since) if since else None,
                                            "until": str(until) if until else None}})
    return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="audit.csv"'})


@router.get("/verify")
def verify_audit(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.AUDITOR, Role.ADMIN)),
) -> dict:
    """Проверка целостности хеш-цепочки (критерий приёмки, раздел 10)."""
    return {"intact": audit.verify_chain(db)}
