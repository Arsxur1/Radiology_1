"""Сборка и сохранение черновика заключения (ТЗ, FR-8)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditAction
from app.models.imaging import Series
from app.models.ml import ConfirmationStatus, Finding, Report
from app.services import audit
from app.services.report_draft import FindingInput, build_draft


def _confirmed_findings_for_study(db: Session, study_id: uuid.UUID) -> list[Finding]:
    return (
        db.execute(
            select(Finding)
            .join(Series, Finding.series_id == Series.id)
            .where(
                Series.study_id == study_id,
                Finding.confirmation_status == ConfirmationStatus.CONFIRMED,
            )
        )
        .scalars()
        .all()
    )


def generate_report_draft(
    db: Session, *, study_id: uuid.UUID, language: str = "ru", actor: str = "system"
) -> Report:
    """Сгенерировать/обновить черновик заключения исследования из подтверждённых находок."""
    findings = _confirmed_findings_for_study(db, study_id)
    inputs = [
        FindingInput(
            finding_id=str(f.id),
            label=f.label,
            code=f.code,
            coding_system=f.coding_system,
            measurements=f.measurements or {},
            confirmed=True,  # выборка уже только по CONFIRMED
        )
        for f in findings
    ]
    draft = build_draft(inputs, language=language)

    report = db.execute(select(Report).where(Report.study_id == study_id)).scalar_one_or_none()
    if report is None:
        report = Report(study_id=study_id)
        db.add(report)
    report.draft_text = draft.text
    report.sentence_map = draft.sentence_map
    report.language = language
    db.flush()
    return report


def finalize_report(
    db: Session, *, report_id: uuid.UUID, physician: str
) -> Report:
    """Финализация черновика — активное действие врача (SR-2), с записью в аудит."""
    report = db.get(Report, report_id)
    if report is None:
        raise ValueError("Черновик не найден")
    report.finalized_by = physician
    db.flush()
    audit.record(
        db,
        actor=physician,
        actor_role="radiologist",
        action=AuditAction.REPORT_FINALIZE,
        entity_type="report",
        entity_id=report.id,
        details={"language": report.language, "sentences": len(report.sentence_map or {})},
    )
    return report
