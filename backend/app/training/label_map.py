"""Сопоставление меток публичных датасетов с нашим словарём находок.

Принцип (ТЗ, SR-1 и раздел 8): модель учится только на НАХОДКАХ (признаках),
никогда на диагнозах. Метки уровня заболевания (пневмония, туберкулёз, ХОБЛ,
опухоль, бронхит…) исключаются из обучения явно и попадают в отчёт с причиной.

Метки, которых нет ни в карте, ни в списке исключений, не угадываются молча:
они возвращаются как «несопоставленные», чтобы врач-эксперт решил их судьбу.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.finding_vocabulary import by_code


def normalize(label: str) -> str:
    """Привести имя метки к виду для сопоставления: регистр, разделители, пробелы."""
    text = label.strip().lower().replace("_", " ").replace("/", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text)


# Метка датасета (нормализованная) → код словаря находок.
FINDING_MAP: dict[str, str] = {
    # CheXpert-метки MIMIC-CXR
    "no finding": "CXR-000",
    "atelectasis": "CXR-102",
    "cardiomegaly": "CXR-500",
    "consolidation": "CXR-100",
    "edema": "CXR-114",
    "enlarged cardiomediastinum": "CXR-406",
    "fracture": "CXR-602",
    "lung lesion": "CXR-112",
    "lung opacity": "CXR-113",
    "pleural effusion": "CXR-200",
    "pleural other": "CXR-203",
    "pneumothorax": "CXR-201",
    "support devices": "CXR-703",
    # Локальные метки VinDr-CXR
    "aortic enlargement": "CXR-403",
    "calcification": "CXR-116",
    "clavicle fracture": "CXR-603",
    "emphysema": "CXR-115",
    "enlarged pa": "CXR-404",
    "ild": "CXR-106",
    "infiltration": "CXR-101",
    "lung cavity": "CXR-105",
    "lung cyst": "CXR-117",
    "mediastinal shift": "CXR-405",
    "nodule mass": "CXR-112",
    "pleural thickening": "CXR-202",
    "pulmonary fibrosis": "CXR-111",
    "rib fracture": "CXR-600",
    # Встречающиеся в педиатрических наборах (VinDr-PCXR и др.)
    "interstitial opacity": "CXR-106",
    "reticulonodular opacity": "CXR-106",
    "peribronchovascular interstitial opacity": "CXR-300",
    "bronchial thickening": "CXR-300",
    "diffuse alveolar opacity": "CXR-113",
    "diffuse aveolar opacity": "CXR-113",  # опечатка в исходной разметке
    "other opacity": "CXR-113",
    "hyperinflation": "CXR-109",
    "bronchiectasis": "CXR-110",
    "situs inversus": "CXR-501",
    # NIH ChestX-ray14 (в т.ч. выходы открытых моделей TorchXRayVision)
    "effusion": "CXR-200",
    "nodule": "CXR-103",
    "mass": "CXR-104",
    "fibrosis": "CXR-111",
}

# Метки уровня заболевания/диагноза — в обучение НЕ идут (SR-1, раздел 8).
EXCLUDED_DIAGNOSES: frozenset[str] = frozenset({
    "pneumonia", "tuberculosis", "copd", "lung tumor", "other disease",
    "other diseases", "bronchitis", "bronchiolitis", "broncho pneumonia",
    "brocho pneumonia", "bronchopneumonia", "covid 19", "lung cancer",
})

# Слишком расплывчатые метки — исключаются, т.к. не соответствуют одной находке.
EXCLUDED_VAGUE: frozenset[str] = frozenset({"other lesion"})


@dataclass
class MappingReport:
    mapped: dict[str, str] = field(default_factory=dict)          # исходная метка → код
    excluded_diagnoses: list[str] = field(default_factory=list)
    excluded_vague: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)             # требуют решения эксперта

    @property
    def codes(self) -> list[str]:
        """Уникальные коды в порядке появления — порядок выходов модели."""
        out: list[str] = []
        for code in self.mapped.values():
            if code not in out:
                out.append(code)
        return out


def map_labels(labels: list[str]) -> MappingReport:
    report = MappingReport()
    for raw in labels:
        key = normalize(raw)
        if key in FINDING_MAP:
            report.mapped[raw] = FINDING_MAP[key]
        elif key in EXCLUDED_DIAGNOSES:
            report.excluded_diagnoses.append(raw)
        elif key in EXCLUDED_VAGUE:
            report.excluded_vague.append(raw)
        else:
            report.unmapped.append(raw)
    return report


def validate_map() -> list[str]:
    """Коды карты, которых нет в словаре находок (должно быть пусто)."""
    return sorted({code for code in FINDING_MAP.values() if by_code(code) is None})
