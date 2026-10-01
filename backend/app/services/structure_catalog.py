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

# КТ брюшной полости.
ABDOMEN_CT_STRUCTURES: tuple[Structure, ...] = (
    Structure("liver", "Печень", "RID58", ("volume_ml",)),
    Structure("spleen", "Селезёнка", "RID86", ("volume_ml",)),
    Structure("kidney_left", "Левая почка", "RID205", ("volume_ml",)),
    Structure("kidney_right", "Правая почка", "RID205", ("volume_ml",)),
    Structure("pancreas", "Поджелудочная железа", "RID170", ("volume_ml",)),
    Structure("gallbladder", "Жёлчный пузырь", "RID187", ("volume_ml",)),
    Structure("stomach", "Желудок", "RID120", ("volume_ml",)),
    Structure("aorta", "Аорта (брюшной отдел)", "RID480", ("volume_ml", "linear_size_mm")),
    Structure("urinary_bladder", "Мочевой пузырь", "RID237", ("volume_ml",)),
    Structure("vertebrae_lumbar", "Поясничные позвонки", "RID2846", ("volume_ml",)),
)

# МРТ головного мозга (структуры/объёмометрия).
BRAIN_MR_STRUCTURES: tuple[Structure, ...] = (
    Structure("brain", "Головной мозг", "RID6434", ("volume_ml",)),
    Structure("ventricles", "Желудочки мозга", "RID6427", ("volume_ml",)),
    Structure("hippocampus_left", "Левый гиппокамп", "RID6480", ("volume_ml",)),
    Structure("hippocampus_right", "Правый гиппокамп", "RID6480", ("volume_ml",)),
)

CATALOG_BY_REGION: dict[str, tuple[Structure, ...]] = {
    "CHEST": CHEST_CT_STRUCTURES,
    "THORAX": CHEST_CT_STRUCTURES,
    "ABDOMEN": ABDOMEN_CT_STRUCTURES,
    "BRAIN": BRAIN_MR_STRUCTURES,
    "HEAD": BRAIN_MR_STRUCTURES,
}

# Ключевые слова протокола/описания → область (для авто-выбора модели/структур).
_REGION_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("chest", "CHEST"),
    ("thorax", "THORAX"),
    ("грудн", "CHEST"),
    ("огк", "CHEST"),          # «рентгенография ОГК» — типичное описание в РУз/СНГ
    ("lung", "CHEST"),
    ("легк", "CHEST"),         # «рентгенография лёгких»
    ("лёгк", "CHEST"),
    # Узбекский (латиница — с ' и ‘, кириллица): «ko'krak qafasi», «o'pka», «qorin bo'shlig'i».
    ("ko'krak", "CHEST"),
    ("ko‘krak", "CHEST"),
    ("кўкрак", "CHEST"),
    ("o'pka", "CHEST"),
    ("o‘pka", "CHEST"),
    ("ўпка", "CHEST"),
    ("abdom", "ABDOMEN"),
    ("брюш", "ABDOMEN"),
    ("живот", "ABDOMEN"),
    ("qorin", "ABDOMEN"),
    ("қорин", "ABDOMEN"),
    ("brain", "BRAIN"),
    ("head", "HEAD"),
    ("мозг", "BRAIN"),
    ("голов", "HEAD"),
)


# Значения DICOM BodyPartExamined (PS3.16 Annex L) → область каталога.
_DICOM_BODY_PARTS = {
    "CHEST": "CHEST", "THORAX": "THORAX", "LUNG": "CHEST", "CHEST_ABDOMEN": "CHEST",
    "ABDOMEN": "ABDOMEN", "HEAD": "HEAD", "SKULL": "HEAD", "BRAIN": "BRAIN",
}


def region_for_study(body_part: str | None, protocol: str | None, description: str | None) -> str | None:
    """Область исследования: сперва DICOM BodyPartExamined, затем протокол/описание."""
    if body_part:
        key = body_part.strip().upper().replace(" ", "_")
        if key in _DICOM_BODY_PARTS:
            return _DICOM_BODY_PARTS[key]
        found = region_from_protocol(body_part)  # «ГРУДНАЯ КЛЕТКА» и т.п.
        if found:
            return found
    return region_from_protocol(protocol, description)


def region_from_protocol(protocol: str | None, description: str | None = None) -> str | None:
    """Определить анатомическую область по протоколу/описанию исследования.

    Возвращает ключ области (CHEST/ABDOMEN/BRAIN…) или None, если не распознано.
    None означает, что гейт применимости не сможет подтвердить body_part и,
    при наличии ограничения по области, откажет (SR-7 — в пользу осторожности).
    """
    text = f"{protocol or ''} {description or ''}".lower()
    for keyword, region in _REGION_KEYWORDS:
        if keyword in text:
            return region
    return None


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
