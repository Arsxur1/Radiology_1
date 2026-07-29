"""Связывание исследования с пациентом через patient_identifier (ТЗ, FR-1).

Автоматическое связывание по нормализованному идентификатору; при
неоднозначности — флаг ручного подтверждения (не связываем молча).
Нормализация решает проблему транслитерации кириллица/латиница (Узбекистан).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.patient import Patient, PatientIdentifier

# Базовая транслитерация кириллица → латиница для сопоставления написаний ФИО.
_CYR_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",  # узбекская кириллица
}


def normalize_identifier(value: str) -> str:
    """Привести написание к сопоставимому виду (регистр, пробелы, транслит)."""
    value = value.strip().lower()
    value = unicodedata.normalize("NFKC", value)
    out = []
    for ch in value:
        out.append(_CYR_LAT.get(ch, ch))
    normalized = "".join(out)
    return " ".join(normalized.split())


@dataclass
class MatchResult:
    patient: Patient | None
    ambiguous: bool
    candidates: list[Patient]
    needs_manual_confirmation: bool


def match_patient(
    db: Session, *, id_type: str, raw_value: str
) -> MatchResult:
    """Найти пациента по идентификатору. Молча связываем только при единственном
    совпадении; при 0 или >1 — требуем действия человека."""
    norm = normalize_identifier(raw_value)
    rows = (
        db.execute(
            select(PatientIdentifier).where(
                PatientIdentifier.id_type == id_type,
                PatientIdentifier.normalized_value == norm,
                PatientIdentifier.active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    patients = list({r.patient for r in rows})
    if len(patients) == 1:
        return MatchResult(patients[0], False, patients, needs_manual_confirmation=False)
    if len(patients) == 0:
        return MatchResult(None, False, [], needs_manual_confirmation=False)
    # Несколько кандидатов — неоднозначность, ручное подтверждение (FR-1).
    return MatchResult(None, True, patients, needs_manual_confirmation=True)
