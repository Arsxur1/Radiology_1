"""Каталог анатомических структур для сегментации (этап 2).

Первая клиническая область — КТ грудной клетки (согласовано с заказчиком).
Метки соответствуют классам TotalSegmentator; коды локализации — RadLex
(по умолчанию, см. VOPROSY-K-TZ.md). Коды-заглушки RID уточняются при интеграции
официального словаря RadLex.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Structure:
    key: str            # метка класса модели (TotalSegmentator)
    label_ru: str
    radlex_code: str    # код RadLex (RID…)
    default_measurements: tuple[str, ...]  # какие измерения считать


# КТ грудной клетки — минимальный набор для первой модели.
CHEST_CT_STRUCTURES: tuple[Structure, ...] = (
    Structure("lung_upper_lobe_left", "Верхняя доля левого лёгкого", "RID1327", ("volume_ml",)),
    Structure("lung_lower_lobe_left", "Нижняя доля левого лёгкого", "RID1328", ("volume_ml",)),
    Structure("lung_upper_lobe_right", "Верхняя доля правого лёгкого", "RID1315", ("volume_ml",)),
    Structure("lung_middle_lobe_right", "Средняя доля правого лёгкого", "RID1316", ("volume_ml",)),
    Structure("lung_lower_lobe_right", "Нижняя доля правого лёгкого", "RID1317", ("volume_ml",)),
    Structure("heart", "Сердце", "RID1385", ("volume_ml",)),
    Structure("aorta", "Аорта", "RID480", ("volume_ml", "linear_size_mm")),
    Structure("trachea", "Трахея", "RID1247", ("volume_ml",)),
    Structure("esophagus", "Пищевод", "RID138", ("volume_ml",)),
    Structure("vertebrae_thoracic", "Грудные позвонки", "RID2846", ("volume_ml",)),
)

CATALOG_BY_REGION: dict[str, tuple[Structure, ...]] = {
    "CHEST": CHEST_CT_STRUCTURES,
    "THORAX": CHEST_CT_STRUCTURES,
}


def structures_for_region(body_part: str | None) -> tuple[Structure, ...]:
    if not body_part:
        return ()
    return CATALOG_BY_REGION.get(body_part.strip().upper(), ())


def structure_by_key(key: str) -> Structure | None:
    for group in CATALOG_BY_REGION.values():
        for s in group:
            if s.key == key:
                return s
    return None
