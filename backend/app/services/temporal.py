"""Сравнение находок во времени (ТЗ, FR-7).

Автоматическое сопоставление находок между исследованиями одного пациента,
расчёт динамики, ряды изменений по времени. **Работает без участия ИИ-моделей**
и обязательно в первой версии.

Сопоставление — по коду локализации (RadLex/SNOMED) и структуре, а не по тексту.
Все расчёты детерминированы: только арифметика над числами измерений.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FindingPoint:
    """Точка временного ряда: находка в конкретном исследовании."""

    study_id: str
    study_date: datetime | None
    finding_id: str
    code: str | None
    structure_key: str | None
    measurements: dict


@dataclass
class MeasurementDelta:
    metric: str
    previous: float
    current: float

    @property
    def absolute(self) -> float:
        return round(self.current - self.previous, 4)

    @property
    def percent(self) -> float | None:
        if self.previous == 0:
            return None
        return round((self.current - self.previous) / abs(self.previous) * 100.0, 2)

    @property
    def direction(self) -> str:
        if self.current > self.previous:
            return "рост"
        if self.current < self.previous:
            return "снижение"
        return "без изменений"


@dataclass
class StructureSeries:
    """Динамика одной структуры по времени."""

    key: str                    # код или structure_key
    label: str | None
    points: list[FindingPoint] = field(default_factory=list)
    deltas: dict[str, MeasurementDelta] = field(default_factory=dict)  # метрика → дельта (посл. пара)


def _series_key(p: FindingPoint) -> str:
    return p.code or p.structure_key or p.finding_id


def _numeric_metrics(measurements: dict) -> dict[str, float]:
    """Плоские числовые метрики находки (объём и т.п.). Вложенные — пропускаются."""
    out: dict[str, float] = {}
    for k, v in (measurements or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = float(v)
    return out


def build_series(points: list[FindingPoint]) -> list[StructureSeries]:
    """Сгруппировать точки по структуре и посчитать динамику по времени (FR-7)."""
    groups: dict[str, list[FindingPoint]] = {}
    labels: dict[str, str | None] = {}
    for p in points:
        key = _series_key(p)
        groups.setdefault(key, []).append(p)
        labels.setdefault(key, p.structure_key or p.code)

    series: list[StructureSeries] = []
    for key, pts in groups.items():
        # Сортировка по времени; None-даты в конец (детерминированный порядок).
        ordered = sorted(pts, key=lambda x: (x.study_date is None, x.study_date or datetime.min))
        deltas: dict[str, MeasurementDelta] = {}
        if len(ordered) >= 2:
            prev_m = _numeric_metrics(ordered[-2].measurements)
            cur_m = _numeric_metrics(ordered[-1].measurements)
            for metric, cur_val in cur_m.items():
                if metric in prev_m:
                    deltas[metric] = MeasurementDelta(metric, prev_m[metric], cur_val)
        series.append(
            StructureSeries(key=key, label=labels.get(key), points=ordered, deltas=deltas)
        )
    series.sort(key=lambda s: s.key)
    return series
