"""Контролируемый словарь находок рентгена/КТ грудной клетки (ТЗ, FR-9, SR-1).

Это НЕ диагноз и НЕ авто-классификация патологии (раздел 8 первой версии их
исключает). Это справочник находок, которым ВРАЧ размечает исследование: выбирает
структурированный признак вместо/вместе со свободным текстом. Каждая такая разметка
через контур FR-9 становится обучающим сигналом для будущих моделей.

Каркас нейтральный (общие находки ОГК, не привязан к одной нозологии) и расширяется
из клинических источников заказчика. Коды — локальные `CXR-*` с полем radlex для
последующего маппинга в RadLex/SNOMED.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FindingConcept:
    code: str                       # локальный код (CXR-...)
    label_ru: str
    group: str                      # группа (лёгкие, плевра, средостение…)
    modalities: tuple[str, ...] = ("CR", "DX", "CT")  # где применимо
    radlex: str | None = None       # код RadLex для будущего маппинга
    note: str | None = None


# Общий набор находок ОГК (расширяемый). Порядок — по группам.
CHEST_FINDINGS: tuple[FindingConcept, ...] = (
    # Норма
    FindingConcept("CXR-000", "Без патологических изменений", "норма"),
    # Лёгочная паренхима
    FindingConcept("CXR-100", "Консолидация (уплотнение)", "лёгкие", radlex="RID43255"),
    FindingConcept("CXR-101", "Инфильтрация", "лёгкие"),
    FindingConcept("CXR-102", "Ателектаз / коллапс", "лёгкие", radlex="RID28493"),
    FindingConcept("CXR-103", "Очаг / узел", "лёгкие", radlex="RID3874"),
    FindingConcept("CXR-104", "Образование (mass)", "лёгкие"),
    FindingConcept("CXR-105", "Полость / каверна", "лёгкие"),
    FindingConcept("CXR-106", "Интерстициальный паттерн", "лёгкие"),
    FindingConcept("CXR-107", "Милиарная диссеминация", "лёгкие"),
    FindingConcept("CXR-108", "Матовое стекло", "лёгкие", modalities=("CT",)),
    FindingConcept("CXR-109", "Гиперинфляция / вздутие", "лёгкие"),
    FindingConcept("CXR-110", "Бронхоэктазы", "лёгкие"),
    FindingConcept("CXR-111", "Фиброз / рубцовые изменения", "лёгкие"),
    # Плевра
    FindingConcept("CXR-200", "Плевральный выпот", "плевра", radlex="RID34539"),
    FindingConcept("CXR-201", "Пневмоторакс", "плевра", radlex="RID5352"),
    FindingConcept("CXR-202", "Утолщение плевры", "плевра"),
    # Дыхательные пути
    FindingConcept("CXR-300", "Перибронхиальные изменения", "дыхательные пути"),
    FindingConcept("CXR-301", "Сужение / компрессия дыхательных путей", "дыхательные пути"),
    FindingConcept("CXR-302", "Инородное тело", "дыхательные пути",
                   note="частая педиатрическая находка"),
    # Средостение и корни
    FindingConcept("CXR-400", "Расширение корня / лимфаденопатия", "средостение и корни"),
    FindingConcept("CXR-401", "Расширение средостения", "средостение и корни"),
    FindingConcept("CXR-402", "Образование средостения", "средостение и корни"),
    # Сердце
    FindingConcept("CXR-500", "Кардиомегалия", "сердце", radlex="RID35075"),
    FindingConcept("CXR-501", "Аномалия положения сердца / situs", "сердце",
                   note="актуально для педиатрии"),
    # Кости и мягкие ткани
    FindingConcept("CXR-600", "Перелом ребра", "кости и мягкие ткани"),
    FindingConcept("CXR-601", "Сколиоз / деформация грудной клетки", "кости и мягкие ткани"),
    # Устройства / инородные материалы (важно в педиатрии/реанимации)
    FindingConcept("CXR-700", "Положение эндотрахеальной трубки", "устройства"),
    FindingConcept("CXR-701", "Положение назогастрального зонда", "устройства"),
    FindingConcept("CXR-702", "Положение центрального катетера", "устройства"),
)


def list_findings(modality: str | None = None, group: str | None = None) -> list[FindingConcept]:
    """Отфильтровать словарь по модальности и/или группе (для UI разметки)."""
    result = list(CHEST_FINDINGS)
    if modality:
        m = modality.strip().upper()
        result = [f for f in result if m in f.modalities]
    if group:
        g = group.strip().lower()
        result = [f for f in result if f.group.lower() == g]
    return result


def groups() -> list[str]:
    """Список групп в порядке первого появления."""
    seen: list[str] = []
    for f in CHEST_FINDINGS:
        if f.group not in seen:
            seen.append(f.group)
    return seen


def by_code(code: str) -> FindingConcept | None:
    for f in CHEST_FINDINGS:
        if f.code == code:
            return f
    return None
