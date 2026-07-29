"""Детерминированные измерения по маскам (ТЗ, FR-6).

Все измерения воспроизводимы: повторный запуск на той же серии той же версией
даёт тот же результат. Здесь только чистые функции над геометрией/статистикой —
никакой недетерминированности (случайности, порядка потоков, времени).

Объёмы — из числа вокселей × объём вокселя. Плотностные характеристики (для КТ —
единицы Хаунсфилда) — детерминированная статистика по вокселям внутри маски.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VoxelSpacing:
    x_mm: float
    y_mm: float
    z_mm: float

    @property
    def voxel_volume_mm3(self) -> float:
        return self.x_mm * self.y_mm * self.z_mm


def volume_ml(voxel_count: int, spacing: VoxelSpacing) -> float:
    """Объём структуры в миллилитрах (1 мл = 1000 мм³). Детерминированно."""
    volume_mm3 = voxel_count * spacing.voxel_volume_mm3
    return round(volume_mm3 / 1000.0, 3)


def linear_size_mm(voxel_extent: int, spacing_mm: float) -> float:
    """Линейный размер по числу вокселей вдоль оси."""
    return round(voxel_extent * spacing_mm, 3)


def density_stats(values: list[float]) -> dict:
    """Детерминированная статистика плотности (напр. HU для КТ).

    Возвращает mean/min/max/std и p05/p50/p95. Порядок вычисления фиксирован,
    поэтому результат воспроизводим при том же входе.
    """
    if not values:
        return {"count": 0}
    ordered = sorted(values)  # детерминированный порядок
    n = len(ordered)
    mean = sum(ordered) / n
    var = sum((v - mean) ** 2 for v in ordered) / n
    return {
        "count": n,
        "mean": round(mean, 3),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
        "std": round(var**0.5, 3),
        "p05": round(_percentile(ordered, 5), 3),
        "p50": round(_percentile(ordered, 50), 3),
        "p95": round(_percentile(ordered, 95), 3),
    }


def ratio(numerator: float, denominator: float) -> float | None:
    """Соотношение (напр. объём доли / объём органа). Детерминированно."""
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _percentile(ordered: list[float], p: float) -> float:
    """Перцентиль методом ближайшего ранга по УЖЕ отсортированному списку."""
    if not ordered:
        return 0.0
    if p <= 0:
        return ordered[0]
    if p >= 100:
        return ordered[-1]
    rank = (p / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac
