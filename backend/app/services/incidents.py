"""Инциденты: сообщение врача → разбор ответственным лицом → закрытие с выводом.

Привязка — к обезличенному исследованию и находке (модель определяется по находке), ФИО в
описание писать не нужно и не следует: по исследованию пациент находится через раскрытие
личности с аудитом. В журнал аудита пишется факт и вид инцидента, а не текст описания.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditAction
from app.models.imaging import Series, Study
from app.models.incident import Incident, IncidentKind, IncidentSeverity, IncidentStatus
from app.models.ml import Finding
from app.services import audit

KIND_LABELS = {
    IncidentKind.AI_MISLEADING: "Находка ИИ могла повлиять на решение",
    IncidentKind.AI_MISSED: "ИИ пропустил значимую находку",
    IncidentKind.WRONG_PATIENT: "Неверная привязка пациента или исследования",
    IncidentKind.SYSTEM_FAILURE: "Сбой системы (недоступность, потеря или искажение данных)",
    IncidentKind.PRIVACY: "Раскрытие персональных данных",
    IncidentKind.OTHER: "Другое",
}
SEVERITY_LABELS = {
    IncidentSeverity.NEAR_MISS: "Замечено до последствий",
    IncidentSeverity.MODERATE: "Повлияло на работу, без вреда пациенту",
    IncidentSeverity.SERIOUS: "Мог быть или причинён вред пациенту — срочный разбор",
}
# Разрешённые переходы статуса; закрытый можно вернуть в разбор (с записью в аудит).
_TRANSITIONS = {
    IncidentStatus.NEW: {IncidentStatus.INVESTIGATING, IncidentStatus.CLOSED},
    IncidentStatus.INVESTIGATING: {IncidentStatus.CLOSED},
    IncidentStatus.CLOSED: {IncidentStatus.INVESTIGATING},
}


class IncidentError(Exception):
    pass


def _text(value: str | None, field: str, *, min_len: int = 10, max_len: int = 4000) -> str:
    v = (value or "").strip()
    if len(v) < min_len:
        raise IncidentError(f"{field}: не короче {min_len} символов")
    if len(v) > max_len:
        raise IncidentError(f"{field}: не длиннее {max_len} символов")
    return v


def report(db: Session, *, actor: str, role: str | None, kind: IncidentKind, severity: IncidentSeverity,
           description: str, study_id: uuid.UUID | None = None, finding_id: uuid.UUID | None = None) -> Incident:
    model_version_id = None
    if finding_id is not None:
        finding = db.get(Finding, finding_id)
        if finding is None:
            raise IncidentError("Находка не найдена")
        if finding.inference_result is not None:
            model_version_id = finding.inference_result.model_version_id
        series = db.get(Series, finding.series_id) if finding.series_id else None
        if study_id is None and series is not None:
            study_id = series.study_id
    if study_id is not None and db.get(Study, study_id) is None:
        raise IncidentError("Исследование не найдено")
    inc = Incident(reported_by=actor, reporter_role=role, kind=kind, severity=severity,
                   status=IncidentStatus.NEW, study_id=study_id, finding_id=finding_id,
                   model_version_id=model_version_id, description=_text(description, "Описание"))
    db.add(inc)
    db.flush()
    audit.record(db, actor=actor, actor_role=role, action=AuditAction.INCIDENT, entity_type="incident",
                 entity_id=inc.id, details={"event": "reported", "kind": kind.value, "severity": severity.value,
                                            "study_id": str(study_id) if study_id else None,
                                            "model_version_id": str(model_version_id) if model_version_id else None})
    return inc


def update(db: Session, incident_id: uuid.UUID, *, actor: str, status: IncidentStatus,
           resolution: str | None = None) -> Incident:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise IncidentError("Инцидент не найден")
    if status != inc.status and status not in _TRANSITIONS[inc.status]:
        raise IncidentError(f"Нельзя перевести из «{inc.status.value}» в «{status.value}»")
    if status == IncidentStatus.CLOSED:
        inc.resolution = _text(resolution, "Вывод разбора")
        inc.closed_by, inc.closed_at = actor, datetime.now(UTC)
    elif resolution:
        inc.resolution = _text(resolution, "Вывод разбора", min_len=1)
    if status != IncidentStatus.CLOSED:
        inc.closed_by = inc.closed_at = None
    previous, inc.status = inc.status, status
    db.flush()
    audit.record(db, actor=actor, actor_role="admin", action=AuditAction.INCIDENT, entity_type="incident",
                 entity_id=inc.id, details={"event": "status", "from": previous.value, "to": status.value})
    return inc


def summary(db: Session) -> dict:
    """Агрегаты для «Пилота» и «Состояния системы»: открытые, серьёзные, по видам."""
    rows = db.execute(select(Incident.kind, Incident.severity, Incident.status)).all()
    open_rows = [r for r in rows if r.status != IncidentStatus.CLOSED]
    return {
        "total": len(rows),
        "open": len(open_rows),
        "open_serious": sum(1 for r in open_rows if r.severity == IncidentSeverity.SERIOUS),
        "by_kind": {KIND_LABELS[k]: n for k, n in Counter(r.kind for r in rows).most_common()},
        "by_status": dict(Counter(r.status.value for r in rows)),
    }
