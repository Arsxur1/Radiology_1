"""Построение содержания DICOM SR заключения (ТЗ, FR-8).

Дерево содержания SR формируется из подтверждённых находок: заголовок-контейнер
и по одному текстовому пункту на находку, каждый трассируется до её finding_id.
Это чистая функция (без pydicom) — тестируема. Сериализация дерева в DICOM SR
через pydicom подключается на стенде (report_export.build_dicom_sr).

Соответствие FR-8: SR собирается только из готовых структурированных данных,
ничего не добавляется; изображения не анализируются.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.report_export import ReportExportInput

# Коды типов узлов SR (DICOM Value Type).
VT_CONTAINER = "CONTAINER"
VT_TEXT = "TEXT"


@dataclass
class SRContentItem:
    value_type: str
    concept_name: str
    text: str | None = None
    finding_id: str | None = None      # трассировка до находки (FR-8)
    children: list[SRContentItem] = field(default_factory=list)


def build_sr_content(data: ReportExportInput) -> SRContentItem:
    """Построить дерево содержания SR из финализированного черновика.

    Корень — CONTAINER «Заключение (черновик)»; дети — TEXT-пункты, по одному на
    предложение, с ссылкой на finding_id из sentence_map.
    """
    root = SRContentItem(
        value_type=VT_CONTAINER,
        concept_name="Diagnostic Imaging Report (draft)",
    )
    for i, sentence in enumerate(data.sentences):
        root.children.append(
            SRContentItem(
                value_type=VT_TEXT,
                concept_name="Finding",
                text=sentence,
                finding_id=data.sentence_map.get(str(i)),
            )
        )
    return root


def sr_traceability_map(root: SRContentItem) -> dict:
    """Сопоставление индекс-пункта → finding_id (для проверки трассируемости)."""
    return {
        str(i): child.finding_id
        for i, child in enumerate(root.children)
        if child.finding_id
    }
