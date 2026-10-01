"""Просмотр исследований и серий (обезличенные данные)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
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
    # Возможен текст с данными пациента в пикселях: врач видит предупреждение, в обучение не идёт.
    burned_in_risk: bool = False


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
    response: Response = None,  # type: ignore[assignment]  # прямой вызов (тесты) — без заголовка
    modality: str | None = None,
    patient_id: uuid.UUID | None = None,
    status: Annotated[str, Query(pattern="^(all|unsigned|signed)$")] = "all",
    date_from: date | None = None,
    date_to: date | None = None,
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[StudyOut]:
    """Рабочий список. Фильтры — на сервере: «неописанные» должны находиться среди всех
    исследований, а не среди последних N (при сотнях исследований в день старое
    неподписанное иначе выпадало бы из очереди). Всего по фильтру — в X-Total-Count."""
    from sqlalchemy import exists, func

    from app.models.ml import Report

    conds = []
    if modality:
        conds.append(Study.modality == modality)
    if patient_id:
        conds.append(Study.patient_id == patient_id)
    if status != "all":
        signed = exists().where(Report.study_id == Study.id, Report.finalized_by.is_not(None))
        conds.append(signed if status == "signed" else ~signed)
    if date_from:
        conds.append(Study.study_date >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        conds.append(Study.study_date < datetime.combine(date_to, datetime.min.time()) + timedelta(days=1))
    by_date = Study.study_date.asc().nullslast() if order == "asc" else Study.study_date.desc().nullslast()
    stmt = select(Study).where(*conds).order_by(by_date, Study.id).limit(limit).offset(offset)
    studies = db.execute(stmt).scalars().all()
    if response is not None:
        total = db.execute(select(func.count()).select_from(Study).where(*conds)).scalar_one()
        response.headers["X-Total-Count"] = str(total)
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
                burned_in_risk=bool(s.burned_in_risk),
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


# --- Предыдущие исследования пациента из PACS (FR-1, FR-7) ---

class PriorOut(BaseModel):
    token: str
    study_date: str | None
    modality: str | None
    description: str | None
    series_count: int | None
    is_current: bool
    imported_study_id: uuid.UUID | None


def _priors_context(db: Session, study_id: uuid.UUID):
    from app.services.pacs import default_node_from_settings

    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Исследование не найдено")
    return study, default_node_from_settings()


@router.get("/{study_id}/pacs-priors", response_model=list[PriorOut])
def pacs_priors(
    study_id: uuid.UUID,
    db: Session = Depends(get_db),
    idmap: Session = Depends(get_idmap_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST, Role.CLINICIAN)),
) -> list[PriorOut]:
    """Исследования того же пациента в PACS клиники — без ФИО, номера карты и исходных UID."""
    from app.services import pacs_priors as pp

    study, node = _priors_context(db, study_id)
    try:
        found = pp.find_priors(db, idmap, study, node=node, finder=pp.pacs.find_studies)
    except pp.PriorsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    audit.record_access(db, user, AuditAction.PATIENT_ACCESS, entity_type="pacs_priors", entity_id=study.id,
                        details={"what": "поиск предыдущих исследований в PACS", "found": len(found)})
    return [PriorOut(**p.__dict__) for p in found]


@router.post("/{study_id}/pacs-priors/{token}/retrieve")
def retrieve_pacs_prior(
    study_id: uuid.UUID,
    token: str,
    db: Session = Depends(get_db),
    idmap: Session = Depends(get_idmap_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST, Role.CLINICIAN)),
) -> dict:
    """Попросить PACS прислать исследование; оно пройдёт обычный приём и обезличивание."""
    from app.services import pacs_priors as pp

    study, node = _priors_context(db, study_id)
    try:
        ok = pp.retrieve_prior(db, idmap, study, token, node=node,
                               finder=pp.pacs.find_studies, mover=pp.pacs.move_study)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except pp.PriorsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    audit.record_access(db, user, AuditAction.STUDY_INGEST, entity_type="pacs_priors", entity_id=study.id,
                        details={"what": "запрос выгрузки предыдущего исследования из PACS", "ok": ok})
    if not ok:
        raise HTTPException(status_code=502, detail="PACS не выполнил выгрузку (проверьте, что узел "
                            "платформы зарегистрирован в PACS как адресат C-MOVE)")
    return {"requested": True, "detail": "Исследование запрошено; появится после приёма и обезличивания"}
