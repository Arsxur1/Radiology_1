"""Запись в аудит-лог (ТЗ, SR-8). Только добавление, с хеш-цепочкой.

Приложение НЕ имеет операций update/delete для audit_log. На уровне СУБД это
дополнительно закрыто правами роли и триггером (миграция 0002). Хеш-цепочка
позволяет обнаружить любой разрыв истории.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.audit import AuditAction, AuditLog


def _compute_hash(prev_hash: str | None, payload: dict) -> str:
    material = (prev_hash or "") + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(material.encode()).hexdigest()


# Ключ advisory lock PostgreSQL для цепочки аудита (произвольная константа).
_AUDIT_LOCK_KEY = 0x6D65647669  # «medvi»


def _lock_chain(db: Session) -> None:
    """Сериализовать запись в аудит до конца транзакции: иначе два параллельных запроса
    возьмут один и тот же «последний» хеш и цепочка разветвится (ложная тревога о подделке)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _AUDIT_LOCK_KEY})


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
    _lock_chain(db)
    last = db.execute(
        select(AuditLog).where(AuditLog.seq.is_not(None)).order_by(AuditLog.seq.desc()).limit(1)
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
        seq=(last.seq + 1) if last else 1,
        prev_hash=prev_hash,
        entry_hash=_compute_hash(prev_hash, payload),
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain_report(db: Session, batch: int = 10000) -> dict:
    """Проверить хеш-цепочку потоком: только нужные колонки, пачками по batch строк.

    Раньше весь журнал загружался в память объектами — на году работы клиники это 14 с и
    ~800 МБ при каждом открытии страницы «Журнал». Возвращает, сколько записей проверено
    и на какой записи цепочка разорвана (если разорвана).
    """
    stmt = (
        select(AuditLog.seq, AuditLog.actor, AuditLog.actor_role, AuditLog.action, AuditLog.entity_type,
               AuditLog.entity_id, AuditLog.details, AuditLog.prev_hash, AuditLog.entry_hash)
        .order_by(AuditLog.seq.asc())
        .execution_options(yield_per=batch)
    )
    prev_hash: str | None = None
    checked = 0
    result = db.execute(stmt)
    try:   # при раннем выходе потоковый курсор надо закрыть явно
        for seq, actor, role, action, etype, eid, details, row_prev, row_hash in result:
            payload = {
                "actor": actor,
                "actor_role": role,
                "action": action.value,
                "entity_type": etype,
                "entity_id": str(eid) if eid else None,
                "details": details,
            }
            if row_prev != prev_hash or row_hash != _compute_hash(prev_hash, payload):
                return {"intact": False, "checked": checked, "broken_at_seq": seq}
            prev_hash = row_hash
            checked += 1
    finally:
        result.close()
    return {"intact": True, "checked": checked, "broken_at_seq": None}


def verify_chain(db: Session) -> bool:
    """Проверить целостность хеш-цепочки аудит-лога (для приёмки, раздел 10)."""
    return verify_chain_report(db)["intact"]


def record_access(db: Session, user, action: AuditAction, *, entity_type: str,
                  entity_id: uuid.UUID | None = None, details: dict | None = None) -> None:
    """Журналировать ДОСТУП к данным (чтение/выгрузку): кто, что, когда (FR-12).

    Фиксируется сразу (отдельный commit): факт доступа не должен теряться, даже если
    дальше обработка запроса упадёт.
    """
    record(
        db, actor=user.subject, actor_role=",".join(sorted(r.value for r in user.roles)),
        action=action, entity_type=entity_type, entity_id=entity_id, details=details or {},
    )
    db.commit()
