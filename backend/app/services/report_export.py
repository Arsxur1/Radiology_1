"""Выгрузка заключения в PDF и DICOM SR (ТЗ, FR-8).

- HTML-рендер (детерминированный, офлайн) → печать в PDF без внешних сервисов.
  Тяжёлый рендер PDF (WeasyPrint/wkhtmltopdf) подключается на стенде; HTML
  самодостаточен и пригоден для печати как есть.
- DICOM SR: структурированный документ из подтверждённых находок. Тело сборки
  через pydicom подключается на стенде (ленивый импорт); здесь — трассируемая
  структура контента.

Экспортируется только финализированный черновик (после активного действия врача).
Каждый пункт трассируется до находки (sentence_map).
"""

from __future__ import annotations

import html
from dataclasses import dataclass


@dataclass
class ReportExportInput:
    study_uid: str
    language: str
    draft_text: str
    sentence_map: dict           # индекс → finding_id
    finalized_by: str | None
    sentences: list[str]         # предложения в порядке sentence_map


_HEADINGS = {
    "ru": {"title": "Заключение (черновик)", "study": "Исследование",
           "by": "Подтвердил", "disclaimer": "Сформировано из подтверждённых врачом находок."},
    "uz": {"title": "Xulosa (qoralama)", "study": "Tekshiruv",
           "by": "Tasdiqladi", "disclaimer": "Shifokor tasdiqlagan topilmalardan shakllantirilgan."},
    "en": {"title": "Report (draft)", "study": "Study",
           "by": "Confirmed by", "disclaimer": "Assembled from physician-confirmed findings."},
}


def render_html(data: ReportExportInput) -> str:
    """Самодостаточный HTML для печати в PDF. Детерминированный, без внешних ресурсов."""
    h = _HEADINGS.get(data.language, _HEADINGS["ru"])
    items = "".join(
        f'<li data-finding-id="{html.escape(data.sentence_map.get(str(i), ""))}">'
        f"{html.escape(s)}</li>"
        for i, s in enumerate(data.sentences)
    )
    by = f"<p>{h['by']}: {html.escape(data.finalized_by)}</p>" if data.finalized_by else ""
    return (
        "<!doctype html><html lang=\"" + html.escape(data.language) + "\"><head>"
        "<meta charset=\"utf-8\"><style>"
        "body{font-family:sans-serif;margin:2rem;color:#111}"
        "h1{font-size:1.3rem}li{margin:.3rem 0}.note{color:#666;font-size:.85rem}"
        "</style></head><body>"
        f"<h1>{h['title']}</h1>"
        f"<p>{h['study']}: {html.escape(data.study_uid)}</p>"
        f"<ol>{items}</ol>{by}"
        f"<p class=\"note\">{h['disclaimer']}</p>"
        "</body></html>"
    )


def build_dicom_sr(data: ReportExportInput):  # pragma: no cover
    """Построить DICOM SR (Basic Text SR) из подтверждённых находок.

    Дерево содержания формируется чистой функцией `report_sr.build_sr_content`
    (тестируемо), здесь оно сериализуется в DICOM через pydicom. Каждый пункт
    трассируется до находки. Изображения не анализируются (FR-8). pydicom
    импортируется лениво — на стенде.
    """
    import pydicom
    from pydicom.dataset import Dataset
    from pydicom.sequence import Sequence

    from app.services.report_sr import VT_CONTAINER, build_sr_content

    root = build_sr_content(data)

    ds = Dataset()
    ds.Modality = "SR"
    ds.SeriesDescription = "medviz report (draft)"
    ds.ValueType = VT_CONTAINER
    ds.ContinuityOfContent = "SEPARATE"
    # Черновик, требующий подтверждения (не верифицированное заключение).
    ds.CompletionFlag = "PARTIAL"
    ds.VerificationFlag = "UNVERIFIED"

    content = []
    for child in root.children:
        item = Dataset()
        item.RelationshipType = "CONTAINS"
        item.ValueType = child.value_type
        item.TextValue = child.text or ""
        # Трассировка до находки — в TrackingUID.
        if child.finding_id:
            item.TrackingUID = child.finding_id
        content.append(item)
    ds.ContentSequence = Sequence(content)

    _ = pydicom  # использование импортированного модуля (метаданные файла — на стенде)
    return ds
