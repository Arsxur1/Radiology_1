"""Запись в аудит-лог (ТЗ, SR-8). Только добавление, с хеш-цепочкой.

Приложение НЕ имеет операций update/delete для audit_log. На уровне СУБД это
дополнительно закрыто правами роли и триггером (миграция 0002). Хеш-цепочка
позволяет обнаружить любой разрыв истории.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditAction, AuditLog


def _compute_hash(prev_hash: str | None, payload: dict) -> str:
    material = (prev_hash or "") + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(material.encode()).hexdigest()


def record(
    db: Session,
    *,
    actor: str,
    action: AuditAction,
    actor_role: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Добавить запись в аудит-лог. Возвращает созданную запись."""
    details = details or {}
    last = db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    prev_hash = last.entry_hash if last else None

    payload = {
        "actor": actor,
        "actor_role": actor_role,
        "action": action.value,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "details": details,
    }
    entry = AuditLog(
        actor=actor,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        prev_hash=prev_hash,
        entry_hash=_compute_hash(prev_hash, payload),
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> bool:
    """Проверить целостность хеш-цепочки аудит-лога (для приёмки, раздел 10)."""
    rows = db.execute(select(AuditLog).order_by(AuditLog.created_at.asc())).scalars().all()
    prev_hash: str | None = None
    for row in rows:
        payload = {
            "actor": row.actor,
            "actor_role": row.actor_role,
            "action": row.action.value,
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id) if row.entity_id else None,
            "details": row.details,
        }
        if row.prev_hash != prev_hash:
            return False
        if row.entry_hash != _compute_hash(prev_hash, payload):
            return False
        prev_hash = row.entry_hash
    return True
