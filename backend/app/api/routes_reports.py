"""Черновик заключения (ТЗ, FR-8). Только из подтверждённых находок, трассируемо."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.imaging import Study
from app.models.ml import Report
from app.services import report_export, report_repo
from app.services.report_draft import UnconfirmedFindingError
from app.services.report_export import ReportExportInput

router = APIRouter(prefix="/reports", tags=["reports"])


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


def _out(r: Report) -> ReportOut:
    return ReportOut(
        id=r.id, study_id=r.study_id, language=r.language,
        draft_text=r.draft_text, sentence_map=r.sentence_map or {},
        finalized_by=r.finalized_by,
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
    except UnconfirmedFindingError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(report)


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: uuid.UUID, db: Session = Depends(get_db)) -> ReportOut:
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _out(report)


@router.get("/{report_id}/export.html", response_class=HTMLResponse)
def export_html(report_id: uuid.UUID, db: Session = Depends(get_db)) -> HTMLResponse:
    """Выгрузка заключения в HTML для печати в PDF (FR-8). Только финализированное."""
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    if not report.finalized_by:
        raise HTTPException(
            status_code=409, detail="Выгрузка возможна только после подтверждения врачом"
        )
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
def sr_content(report_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
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
