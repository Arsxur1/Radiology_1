"""Справочник находок для разметки врачом (ТЗ, FR-9). Только чтение словаря."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import finding_vocabulary

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])


class ConceptOut(BaseModel):
    code: str
    label_ru: str
    group: str
    modalities: list[str]
    radlex: str | None
    note: str | None


@router.get("/chest-findings", response_model=list[ConceptOut])
def chest_findings(modality: str | None = None, group: str | None = None) -> list[ConceptOut]:
    """Словарь находок ОГК для UI разметки. Фильтры по модальности и группе.

    Это структурированные находки для фиксации ВРАЧОМ (SR-1: не диагноз), которые
    питают контур обучения (FR-9). Не является авто-классификацией (раздел 8).
    """
    items = finding_vocabulary.list_findings(modality=modality, group=group)
    return [
        ConceptOut(
            code=c.code, label_ru=c.label_ru, group=c.group,
            modalities=list(c.modalities), radlex=c.radlex, note=c.note,
        )
        for c in items
    ]


@router.get("/chest-findings/groups", response_model=list[str])
def chest_finding_groups() -> list[str]:
    return finding_vocabulary.groups()
