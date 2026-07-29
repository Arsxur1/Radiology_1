"""Контроль дрейфа (ТЗ, FR-11).

Два направления:
1. Распределение входных данных: новый аппарат, изменённый протокол, смещение
   возрастного состава — с оповещением.
2. Доля отклонённых врачом результатов по срезам: рост доли отклонений на
   конкретном аппарате означает деградацию, невидимую по общей метрике.

Метрики раздельны по клинике (FR-11).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.drift import DataDriftMetric
from app.models.imaging import Series, Study
from app.models.ml import Correction, CorrectionType


@dataclass
class RejectionRate:
    slice_dimension: str
    slice_value: str
    total: int
    rejected: int

    @property
    def rate(self) -> float:
        return self.rejected / self.total if self.total else 0.0


def compute_rejection_rate(corrections: list[tuple[str, str]]) -> float:
    """Доля отклонений среди правок. corrections: список (correction_type, _).

    Чистая функция для тестов: rejected / total.
    """
    if not corrections:
        return 0.0
    rejected = sum(1 for t, _ in corrections if t == CorrectionType.REJECTED.value)
    return rejected / len(corrections)


def rejection_rate_by_manufacturer(db: Session) -> list[RejectionRate]:
    """Доля отклонений по производителю аппарата (срез для FR-11)."""
    rows = db.execute(
        select(
            Study.manufacturer,
            Correction.correction_type,
            func.count().label("n"),
        )
        .join(Series, Correction.series_id == Series.id)
        .join(Study, Series.study_id == Study.id)
        .group_by(Study.manufacturer, Correction.correction_type)
    ).all()

    agg: dict[str, dict[str, int]] = {}
    for manufacturer, ctype, n in rows:
        key = manufacturer or "unknown"
        bucket = agg.setdefault(key, {"total": 0, "rejected": 0})
        bucket["total"] += n
        if ctype == CorrectionType.REJECTED:
            bucket["rejected"] += n

    return [
        RejectionRate(
            slice_dimension="manufacturer",
            slice_value=key,
            total=vals["total"],
            rejected=vals["rejected"],
        )
        for key, vals in sorted(agg.items())
    ]


def known_manufacturers(db: Session) -> set[str]:
    rows = db.execute(select(Study.manufacturer).distinct()).scalars().all()
    return {m for m in rows if m}


def detect_new_device(db: Session, incoming_manufacturer: str | None) -> bool:
    """Появился ли ранее не встречавшийся аппарат (оповещение о дрейфе входа)."""
    if not incoming_manufacturer:
        return False
    return incoming_manufacturer not in known_manufacturers(db)


def record_metric(
    db: Session,
    *,
    slice_dimension: str,
    slice_value: str,
    metrics: dict,
    clinic: str | None = None,
) -> DataDriftMetric:
    m = DataDriftMetric(
        slice_dimension=slice_dimension,
        slice_value=slice_value,
        clinic=clinic,
        metrics=metrics,
    )
    db.add(m)
    db.flush()
    return m
