"""Журнал инцидентов (ТЗ, раздел 9 п. 7; пострегистрационный надзор).

Сообщают врач, клиницист и администратор; разбирает и закрывает администратор
(ответственное лицо). Аудитор видит все записи, остальные — только свои.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.incident import Incident, IncidentKind, IncidentSeverity, IncidentStatus
from app.services import incidents
from app.services.incidents import IncidentError

router = APIRouter(prefix="/incidents", tags=["incidents"])

_REPORTERS = (Role.RADIOLOGIST, Role.CLINICIAN, Role.ADMIN)


class IncidentIn(BaseModel):
    kind: IncidentKind
    severity: IncidentSeverity
    description: str
    study_id: uuid.UUID | None = None
    finding_id: uuid.UUID | None = None


class IncidentUpdateIn(BaseModel):
    status: IncidentStatus
    resolution: str | None = None


class IncidentOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    reported_by: str
    reporter_role: str | None
    kind: str
    kind_label: str
    severity: str
    severity_label: str
    status: str
    study_id: uuid.UUID | None
    finding_id: uuid.UUID | None
    model_version_id: uuid.UUID | None
    description: str
    resolution: str | None
    closed_by: str | None
    closed_at: datetime | None


def _out(i: Incident) -> IncidentOut:
    return IncidentOut(
        id=i.id, created_at=i.created_at, reported_by=i.reported_by, reporter_role=i.reporter_role,
        kind=i.kind.value, kind_label=incidents.KIND_LABELS[i.kind],
        severity=i.severity.value, severity_label=incidents.SEVERITY_LABELS[i.severity],
        status=i.status.value, study_id=i.study_id, finding_id=i.finding_id,
        model_version_id=i.model_version_id, description=i.description, resolution=i.resolution,
        closed_by=i.closed_by, closed_at=i.closed_at,
    )


@router.get("/kinds")
def kinds() -> dict:
    """Закрытые списки видов и тяжести (подписи — для формы)."""
    return {
        "kinds": [{"value": k.value, "label": v} for k, v in incidents.KIND_LABELS.items()],
        "severities": [{"value": k.value, "label": v} for k, v in incidents.SEVERITY_LABELS.items()],
    }


@router.post("", response_model=IncidentOut, status_code=201)
def report(
    payload: IncidentIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*_REPORTERS)),
) -> IncidentOut:
    try:
        inc = incidents.report(
            db, actor=user.subject, role=",".join(sorted(r.value for r in user.roles)),
            kind=payload.kind, severity=payload.severity, description=payload.description,
            study_id=payload.study_id, finding_id=payload.finding_id,
        )
        db.commit()
    except IncidentError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _out(inc)


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    status: IncidentStatus | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*_REPORTERS, Role.AUDITOR)),
) -> list[IncidentOut]:
    q = select(Incident).order_by(Incident.created_at.desc()).limit(500)
    if not (user.has(Role.ADMIN) or user.has(Role.AUDITOR)):
        q = q.where(Incident.reported_by == user.subject)
    if status is not None:
        q = q.where(Incident.status == status)
    return [_out(i) for i in db.execute(q).scalars()]


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN, Role.AUDITOR)),
) -> dict:
    return incidents.summary(db)


@router.patch("/{incident_id}", response_model=IncidentOut)
def update(
    incident_id: uuid.UUID,
    payload: IncidentUpdateIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> IncidentOut:
    try:
        inc = incidents.update(db, incident_id, actor=user.subject, status=payload.status,
                               resolution=payload.resolution)
        db.commit()
    except IncidentError as e:
        db.rollback()
        code = 404 if "не найден" in str(e) else 409
        raise HTTPException(status_code=code, detail=str(e)) from e
    return _out(inc)
