"""Просмотр исследований и серий (обезличенные данные)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require_roles
from app.core.roles import Role
from app.db.session import get_db, get_idmap_db
from app.models.audit import AuditAction
from app.models.imaging import Series, Study
from app.services import audit

router = APIRouter(prefix="/studies", tags=["studies"])


class SeriesOut(BaseModel):
    id: uuid.UUID
    series_instance_uid: str
    modality: str
    description: str | None
    instance_count: int | None
    slice_thickness_mm: float | None
    lossy_compressed: bool
    is_3d_capable: bool


class StudyOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    study_instance_uid: str
    modality: str
    description: str | None
    manufacturer: str | None
    series: list[SeriesOut]
    study_date: datetime | None = None
    patient_age_years: float | None = None
    # Черновики находок ИИ, ожидающие решения врача (видимые в текущем режиме).
    ai_pending: int = 0
    # none — заключения нет; draft — черновик; signed — подписано.
    report_status: str = "none"


@router.get("", response_model=list[StudyOut])
def list_studies(
    modality: str | None = None,
    patient_id: uuid.UUID | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[StudyOut]:
    stmt = select(Study).order_by(Study.study_date.desc().nullslast()).limit(limit)
    if modality:
        stmt = stmt.where(Study.modality == modality)
    if patient_id:
        stmt = stmt.where(Study.patient_id == patient_id)
    studies = db.execute(stmt).scalars().all()
    pending, reports = _worklist_status(db, [s.id for s in studies])
    return [_to_study_out(s, pending.get(s.id, 0), reports.get(s.id, "none")) for s in studies]


@router.get("/{study_id}", response_model=StudyOut)
def get_study(
    study_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> StudyOut:
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Исследование не найдено")
    audit.record_access(db, user, AuditAction.PATIENT_ACCESS, entity_type="study", entity_id=study.id,
                        details={"what": "открыто исследование", "patient_id": str(study.patient_id)})
    pending, reports = _worklist_status(db, [study.id])
    return _to_study_out(study, pending.get(study.id, 0), reports.get(study.id, "none"))


def _worklist_status(db: Session, study_ids: list[uuid.UUID]) -> tuple[dict, dict]:
    """Сколько черновиков классификатора ждут решения и статус заключения — по исследованиям."""
    from sqlalchemy import func

    from app.models.ml import ConfirmationStatus, Finding, FindingSource, InferenceResult, ModelVersion, Report
    from app.services.mode_state import model_results_visible

    if not study_ids:
        return {}, {}
    rows = db.execute(
        select(Series.study_id, Series.modality, func.count())
        .join(Finding, Finding.series_id == Series.id)
        .join(InferenceResult, Finding.inference_result_id == InferenceResult.id)
        .join(ModelVersion, InferenceResult.model_version_id == ModelVersion.id)
        .where(
            Series.study_id.in_(study_ids),
            ModelVersion.task == "classification",
            Finding.source == FindingSource.MODEL,
            Finding.confirmation_status == ConfirmationStatus.PENDING,
            InferenceResult.shadow_run.is_(False),
        )
        .group_by(Series.study_id, Series.modality)
    ).all()
    visible: dict[str | None, bool] = {}
    pending: dict = {}
    for study_id, modality, n in rows:
        if modality not in visible:
            visible[modality] = model_results_visible(db, modality)
        if visible[modality]:
            pending[study_id] = pending.get(study_id, 0) + n
    reports = {
        sid: ("signed" if fin else "draft")
        for sid, fin in db.execute(
            select(Report.study_id, Report.finalized_by).where(Report.study_id.in_(study_ids))
        ).all()
    }
    return pending, reports


def _to_study_out(study: Study, ai_pending: int = 0, report_status: str = "none") -> StudyOut:
    return StudyOut(
        study_date=study.study_date,
        patient_age_years=study.patient_age_years,
        ai_pending=ai_pending,
        report_status=report_status,
        id=study.id,
        patient_id=study.patient_id,
        study_instance_uid=study.study_instance_uid,
        modality=study.modality,
        description=study.description,
        manufacturer=study.manufacturer,
        series=[
            SeriesOut(
                id=s.id,
                series_instance_uid=s.series_instance_uid,
                modality=s.modality,
                description=s.description,
                instance_count=s.instance_count,
                slice_thickness_mm=s.slice_thickness_mm,
                lossy_compressed=s.lossy_compressed,
                is_3d_capable=s.is_3d_capable(),
            )
            for s in study.series
        ],
    )


@router.get("/series/{series_id}/preview")
def series_preview(
    series_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.RADIOLOGIST, Role.ADMIN, Role.RESEARCHER)),
) -> Response:
    """PNG-превью снимка из обезличенного контура (clean-Orthanc) — фон для тепловой карты."""
    from app.services.orthanc import clean_client

    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    client = clean_client()
    try:
        png = client.series_preview_png(series.series_instance_uid)
    finally:
        client.close()
    if png is None:
        raise HTTPException(status_code=404, detail="Снимок серии не найден в хранилище")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


# Допустимые цели раскрытия личности (purpose of use) — фиксируются в журнале аудита.
IDENTITY_PURPOSES = {
    "report": "подписание / передача заключения",
    "clinical": "клиническое решение по пациенту",
    "comparison": "сопоставление с предыдущими исследованиями в PACS",
}


class IdentityOut(BaseModel):
    patient_name: str | None
    patient_mrn: str | None
    original_study_instance_uid: str | None
    purpose: str


@router.get("/{study_id}/identity", response_model=IdentityOut)
def reveal_identity(
    study_id: uuid.UUID,
    purpose: str,
    response: Response,
    db: Session = Depends(get_db),
    idmap: Session = Depends(get_idmap_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST, Role.CLINICIAN)),
) -> IdentityOut:
    """Раскрыть реальные данные пациента для лечащего/описывающего врача (SR-9).

    Данные берутся из идентифицирующего контура и не сохраняются в доверенном.
    Каждое раскрытие — с целью — пишется в журнал аудита ДО выдачи данных.
    """
    from app.models.idmap import PatientPseudonymMap

    if purpose not in IDENTITY_PURPOSES:
        raise HTTPException(status_code=422, detail={"allowed_purposes": IDENTITY_PURPOSES})
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Исследование не найдено")
    row = idmap.execute(
        select(PatientPseudonymMap)
        .where(PatientPseudonymMap.pseudonym_study_instance_uid == study.study_instance_uid)
        .order_by(PatientPseudonymMap.created_at.desc())
    ).scalars().first()
    audit.record_access(db, user, AuditAction.PATIENT_ACCESS, entity_type="identity", entity_id=study.id,
                        details={"what": "раскрытие личности пациента", "purpose": purpose,
                                 "patient_id": str(study.patient_id), "found": row is not None})
    if row is None:
        raise HTTPException(status_code=404, detail="Нет данных о пациенте в идентифицирующем контуре")
    response.headers["Cache-Control"] = "no-store"
    name = (row.real_name or "").replace("^", " ").strip() or None
    return IdentityOut(patient_name=name, patient_mrn=row.real_mrn,
                       original_study_instance_uid=row.real_study_instance_uid,
                       purpose=IDENTITY_PURPOSES[purpose])
