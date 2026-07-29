"""Выборка находок пациента для сравнения во времени (ТЗ, FR-7)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imaging import Series, Study
from app.models.ml import ConfirmationStatus, Finding
from app.services.temporal import FindingPoint, StructureSeries, build_series


def collect_patient_points(
    db: Session, *, patient_id: uuid.UUID, confirmed_only: bool = True
) -> list[FindingPoint]:
    """Собрать точки временного ряда по всем исследованиям пациента.

    По умолчанию берутся только подтверждённые находки: динамика строится по
    тому, что подтвердил врач (согласуется с разделом 11).
    """
    stmt = (
        select(Finding, Series, Study)
        .join(Series, Finding.series_id == Series.id)
        .join(Study, Series.study_id == Study.id)
        .where(Study.patient_id == patient_id)
    )
    if confirmed_only:
        stmt = stmt.where(Finding.confirmation_status == ConfirmationStatus.CONFIRMED)

    points: list[FindingPoint] = []
    for finding, _series, study in db.execute(stmt).all():
        structure_key = None
        if finding.coordinates and isinstance(finding.coordinates, dict):
            structure_key = finding.coordinates.get("structure_key")
        points.append(
            FindingPoint(
                study_id=str(study.id),
                study_date=study.study_date,
                finding_id=str(finding.id),
                code=finding.code,
                structure_key=structure_key,
                measurements=finding.measurements or {},
            )
        )
    return points


def patient_series(
    db: Session, *, patient_id: uuid.UUID, confirmed_only: bool = True
) -> list[StructureSeries]:
    return build_series(collect_patient_points(db, patient_id=patient_id, confirmed_only=confirmed_only))
