"""Путь через DICOMweb (ТЗ, FR-1): QIDO-RS поиск, WADO-RS выгрузка.

Используется, если внешний PACS поддерживает DICOMweb. Выгруженные объекты
загружаются в приёмный Orthanc (raw), откуда идёт штатное обезличивание (SR-9).
"""

from __future__ import annotations

from app.services.pacs import FoundStudy, PacsNode, QueryOutcome, StudyQuery


def qido_find_studies(node: PacsNode, query: StudyQuery, timeout: float = 30.0) -> QueryOutcome:
    """QIDO-RS: поиск исследований. Возвращает нормализованный список."""
    import httpx  # локальный импорт: чистые функции разбора не требуют сети

    if not node.dicomweb_base_url:
        raise ValueError("Для узла не задан dicomweb_base_url")
    outcome = QueryOutcome()
    url = node.dicomweb_base_url.rstrip("/") + "/studies"
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, params=query.to_qido_params())
        resp.raise_for_status()
        for item in resp.json():
            outcome.studies.append(_parse_qido_study(item))
    return outcome


def _tag(item: dict, tag: str) -> str | None:
    """Достать первое значение DICOM-тега из QIDO JSON-ответа."""
    node = item.get(tag)
    if not node:
        return None
    values = node.get("Value")
    if not values:
        return None
    v = values[0]
    if isinstance(v, dict):  # PN (PatientName) → {"Alphabetic": "..."}
        return v.get("Alphabetic")
    return str(v)


def _parse_qido_study(item: dict) -> FoundStudy:
    return FoundStudy(
        study_instance_uid=_tag(item, "0020000D") or "",
        patient_id=_tag(item, "00100020"),
        study_date=_tag(item, "00080020"),
        modality=_tag(item, "00080061"),          # ModalitiesInStudy
        description=_tag(item, "00081030"),
        series_count=_safe_int(_tag(item, "00201206")),
    )


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
