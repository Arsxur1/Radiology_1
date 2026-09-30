"""Черновик заключения (ТЗ, FR-8). Только из подтверждённых находок, трассируемо."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db, get_idmap_db
from app.models.audit import AuditAction
from app.models.imaging import Study
from app.models.ml import Report
from app.services import audit, report_export, report_repo
from app.services.report_draft import UnconfirmedFindingError
from app.services.report_export import ReportExportInput

router = APIRouter(prefix="/reports", tags=["reports"])

# Кто читает заключения: врачи и клиницисты; админ; не исследователь (только обезличенные данные).
REPORT_READERS = (Role.RADIOLOGIST, Role.CLINICIAN, Role.ADMIN, Role.AUDITOR)


class GenerateIn(BaseModel):
    study_id: uuid.UUID
    language: str = "ru"


class ReportOut(BaseModel):
    id: uuid.UUID
    study_id: uuid.UUID
    language: str
    draft_text: str | None
    sentence_map: dict
    finalized_by: str | None
    # Предупреждение о непроверенной терминологии перевода (показывается врачу).
    terminology_note: str | None = None


def _out(r: Report) -> ReportOut:
    from app.services.i18n_uz import UZ_GLOSSARY_APPROVED

    note = None
    if r.language == "uz" and not UZ_GLOSSARY_APPROVED:
        note = ("Узбекская терминология — черновой перевод, не проверена врачом-носителем "
                "(docs/GLOSSARY-UZ.md). Сверьте названия перед подписью.")
    return ReportOut(
        id=r.id, study_id=r.study_id, language=r.language,
        draft_text=r.draft_text, sentence_map=r.sentence_map or {},
        finalized_by=r.finalized_by, terminology_note=note,
    )


@router.post("/generate", response_model=ReportOut)
def generate(
    payload: GenerateIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST, Role.ADMIN)),
) -> ReportOut:
    """Собрать черновик из подтверждённых находок исследования (FR-8)."""
    try:
        report = report_repo.generate_report_draft(
            db, study_id=payload.study_id, language=payload.language, actor=user.subject,
        )
        db.commit()
    except (UnconfirmedFindingError, report_repo.ReportConflict) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(report)


@router.get("/by-study/{study_id}", response_model=ReportOut)
def get_study_report(
    study_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(*REPORT_READERS)),
) -> ReportOut:
    """Заключение исследования (черновик или подписанное) — чтобы при повторном открытии
    врач видел его сразу, а подписанное можно было отправить в PACS позже."""
    from sqlalchemy import select

    rows = db.execute(select(Report).where(Report.study_id == study_id)).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="Заключения ещё нет")
    # По правилам заключение одно; если данных больше — подписанное важнее, затем самое свежее.
    report = max(rows, key=lambda r: (bool(r.finalized_by), r.updated_at or r.created_at))
    return _out(report)


@router.get("/{report_id}", response_model=ReportOut)
def get_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(*REPORT_READERS)),
) -> ReportOut:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    return _out(report)


@router.post("/{report_id}/finalize", response_model=ReportOut)
def finalize(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> ReportOut:
    """Финализация — активное действие врача (SR-2). Черновик становится заключением."""
    try:
        report = report_repo.finalize_report(db, report_id=report_id, physician=user.subject)
        db.commit()
    except report_repo.ReportConflict as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _out(report)


@router.get("/{report_id}/export.html", response_class=HTMLResponse)
def export_html(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*REPORT_READERS)),
) -> HTMLResponse:
    """Выгрузка заключения в HTML для печати в PDF (FR-8). Только финализированное."""
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    if not report.finalized_by:
        raise HTTPException(
            status_code=409, detail="Выгрузка возможна только после подтверждения врачом"
        )
    audit.record_access(db, user, AuditAction.EXPORT, entity_type="report", entity_id=report.id,
                        details={"what": "выгрузка заключения (HTML)", "study_id": str(report.study_id)})
    study = db.get(Study, report.study_id)
    data = ReportExportInput(
        study_uid=study.study_instance_uid if study else str(report.study_id),
        language=report.language,
        draft_text=report.draft_text or "",
        sentence_map=report.sentence_map or {},
        finalized_by=report.finalized_by,
        sentences=_split_sentences(report.draft_text or ""),
    )
    return HTMLResponse(content=report_export.render_html(data))


@router.get("/{report_id}/sr-content")
def sr_content(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*REPORT_READERS)),
) -> dict:
    """Структура содержания DICOM SR с трассировкой пункт → находка (FR-8).

    Сам бинарный SR (Basic Text SR) собирается через pydicom на стенде; здесь —
    проверяемое дерево содержания. Только финализированное заключение.
    """
    from app.services.report_sr import build_sr_content, sr_traceability_map

    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    if not report.finalized_by:
        raise HTTPException(
            status_code=409, detail="Выгрузка возможна только после подтверждения врачом"
        )
    audit.record_access(db, user, AuditAction.EXPORT, entity_type="report", entity_id=report.id,
                        details={"what": "выгрузка заключения (DICOM SR)", "study_id": str(report.study_id)})
    study = db.get(Study, report.study_id)
    data = ReportExportInput(
        study_uid=study.study_instance_uid if study else str(report.study_id),
        language=report.language,
        draft_text=report.draft_text or "",
        sentence_map=report.sentence_map or {},
        finalized_by=report.finalized_by,
        sentences=_split_sentences(report.draft_text or ""),
    )
    root = build_sr_content(data)
    return {
        "value_type": root.value_type,
        "items": [
            {"text": c.text, "finding_id": c.finding_id} for c in root.children
        ],
        "traceability": sr_traceability_map(root),
    }


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in text.split(". ") if p.strip()]
    return [p if p.endswith(".") else p + "." for p in parts]


@router.post("/{report_id}/send-to-pacs")
def send_to_pacs(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    idmap: Session = Depends(get_idmap_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> dict:
    """Отправить подписанное заключение в PACS клиники как DICOM SR (C-STORE).

    SR кладётся к настоящему пациенту и исследованию: реальные идентификаторы берутся
    из идентифицирующего контура только в памяти на время отправки. Повторная отправка
    заменяет тот же документ (UID детерминированы). Факт отправки — в журнал аудита.
    """
    from sqlalchemy import select

    from app.models.idmap import PatientPseudonymMap
    from app.services import pacs
    from app.services.report_export import SrIdentity, build_dicom_sr

    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    if not report.finalized_by:
        raise HTTPException(status_code=409, detail="Отправка возможна только после подписи врачом")
    node = pacs.default_node_from_settings()
    if node is None:
        raise HTTPException(status_code=503, detail="Узел PACS не настроен (PACS_AET/PACS_HOST/PACS_PORT в .env)")
    study = db.get(Study, report.study_id)
    row = idmap.execute(
        select(PatientPseudonymMap)
        .where(PatientPseudonymMap.pseudonym_study_instance_uid == study.study_instance_uid)
        .order_by(PatientPseudonymMap.created_at.desc())
    ).scalars().first()
    if row is None or not row.real_study_instance_uid or not row.real_mrn:
        raise HTTPException(status_code=409, detail="Нет исходных идентификаторов исследования — "
                            "SR не к чему привязать в PACS")
    data = ReportExportInput(
        study_uid=study.study_instance_uid, language=report.language, draft_text=report.draft_text or "",
        sentence_map=report.sentence_map or {}, finalized_by=report.finalized_by,
        sentences=_split_sentences(report.draft_text or ""),
    )
    ds = build_dicom_sr(
        data, SrIdentity(patient_id=row.real_mrn, patient_name=row.real_name or "",
                         study_instance_uid=row.real_study_instance_uid),
        report_id=str(report.id), verified_at=report.updated_at or report.created_at,
        study_date=study.study_date,
    )
    try:
        statuses = pacs.store_datasets(node, [ds])
    except pacs.PacsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    ok = statuses == [0]
    audit.record_access(db, user, AuditAction.EXPORT, entity_type="report", entity_id=report.id,
                        details={"what": "заключение (DICOM SR) отправлено в PACS", "ok": ok,
                                 "status": statuses[0] if statuses else None,
                                 "sop_instance_uid": str(ds.SOPInstanceUID)})
    if not ok:
        raise HTTPException(status_code=502, detail=f"PACS не принял заключение (статус {statuses})")
    return {"sent": True, "sop_instance_uid": str(ds.SOPInstanceUID)}
