"""Экспорт обучающего набора из накопленных правок (ТЗ, FR-9).

Разметка получена как побочный результат клинической работы. Экспорт с
фильтрами по модальности, аппарату, возрасту и качеству разметки — для
офлайн-дообучения на ОТДЕЛЬНОМ контуре (FR-10, п. 3). Экспорт всегда
обезличен (SR-9): идёт из доверенного контура, PHI отсутствует по построению.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imaging import Series, Study
from app.models.ml import Correction, CorrectionType, Finding


@dataclass
class ExportFilters:
    modality: str | None = None
    manufacturer: str | None = None
    # Только правки этих типов (по умолчанию — все: подтверждения тоже сигнал).
    correction_types: list[CorrectionType] = field(
        default_factory=lambda: list(CorrectionType)
    )
    # Качество разметки: минимальное время, затраченное врачом (сек).
    # Слишком быстрые «подтверждения» могут быть шумом — отсекаются.
    min_time_spent_seconds: float | None = None
    require_3d_capable: bool = False


@dataclass
class ExportItem:
    correction_id: str
    series_instance_uid: str
    modality: str
    manufacturer: str | None
    correction_type: str
    before: dict | None
    after: dict | None
    time_spent_seconds: float | None
    finding_source: str | None


def build_query(filters: ExportFilters):
    """Собрать выборку правок по фильтрам. Вынесено для тестируемости."""
    stmt = (
        select(Correction, Series, Study, Finding)
        .join(Series, Correction.series_id == Series.id)
        .join(Study, Series.study_id == Study.id)
        .outerjoin(Finding, Correction.finding_id == Finding.id)
    )
    if filters.correction_types:
        stmt = stmt.where(Correction.correction_type.in_(filters.correction_types))
    if filters.modality:
        stmt = stmt.where(Series.modality == filters.modality)
    if filters.manufacturer:
        stmt = stmt.where(Study.manufacturer == filters.manufacturer)
    if filters.min_time_spent_seconds is not None:
        stmt = stmt.where(
            Correction.time_spent_seconds >= filters.min_time_spent_seconds
        )
    return stmt


def export(db: Session, filters: ExportFilters | None = None) -> list[ExportItem]:
    filters = filters or ExportFilters()
    rows = db.execute(build_query(filters)).all()
    items: list[ExportItem] = []
    for correction, series, study, finding in rows:
        if filters.require_3d_capable and not series.is_3d_capable():
            continue
        items.append(
            ExportItem(
                correction_id=str(correction.id),
                series_instance_uid=series.series_instance_uid,
                modality=series.modality,
                manufacturer=study.manufacturer,
                correction_type=correction.correction_type.value,
                before=correction.before,
                after=correction.after,
                time_spent_seconds=correction.time_spent_seconds,
                finding_source=finding.source.value if finding else None,
            )
        )
    return items
