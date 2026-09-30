"""Выгрузка заключения в PDF и DICOM SR (ТЗ, FR-8).

- HTML-рендер (детерминированный, офлайн) → печать в PDF без внешних сервисов.
  Тяжёлый рендер PDF (WeasyPrint/wkhtmltopdf) подключается на стенде; HTML
  самодостаточен и пригоден для печати как есть.
- DICOM SR: Basic Text SR из подписанного заключения (build_dicom_sr); уходит в PACS
  клиники по C-STORE к исходному исследованию (POST /reports/{id}/send-to-pacs).

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


@dataclass
class SrIdentity:
    """Реальные данные пациента и исследования для SR, уходящего в PACS клиники.

    Берутся из идентифицирующего контура только в момент отправки и живут в памяти:
    без них SR лёг бы в PACS отдельным «псевдопациентом», и клиницист его не нашёл бы.
    """

    patient_id: str
    patient_name: str
    study_instance_uid: str


def _uid(*parts: str) -> str:
    """Детерминированный UID: повторная отправка заменяет тот же документ в PACS."""
    from pydicom.uid import generate_uid

    return generate_uid(entropy_srcs=["medviz-sr", *parts])


def _code(value: str, scheme: str, meaning: str):
    from pydicom.dataset import Dataset

    c = Dataset()
    c.CodeValue, c.CodingSchemeDesignator, c.CodeMeaning = value, scheme, meaning
    return c


def build_dicom_sr(data: ReportExportInput, identity: SrIdentity, *, report_id: str, verified_at,
                   study_date=None, organization: str = "medviz"):
    """DICOM Basic Text SR из подписанного заключения (FR-8).

    Корень — CONTAINER «Diagnostic imaging report» (LOINC 18748-4), пункты — TEXT
    «Finding» (DCM 121071), по одному на предложение. Трассировка пункта до находки —
    ObservationUID, выведенный из finding_id. Изображения не анализируются: SR собран
    только из подтверждённых находок, VERIFIED — подписан врачом.
    """
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.sequence import Sequence
    from pydicom.uid import ExplicitVRLittleEndian

    basic_text_sr = "1.2.840.10008.5.1.4.1.1.88.11"
    when = verified_at.strftime("%Y%m%d%H%M%S")
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = basic_text_sr
    ds.SpecificCharacterSet = "ISO_IR 192"          # кириллица и узбекская латиница
    ds.SOPClassUID = basic_text_sr
    ds.SOPInstanceUID = _uid(report_id, "instance")
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

    # Пациент и исследование — настоящие (исследование в PACS клиники).
    ds.PatientName = identity.patient_name
    ds.PatientID = identity.patient_id
    ds.PatientBirthDate = ""
    ds.PatientSex = ""
    ds.StudyInstanceUID = identity.study_instance_uid
    ds.StudyDate = study_date.strftime("%Y%m%d") if study_date else ""
    ds.StudyTime = ""
    ds.ReferringPhysicianName = ""
    ds.StudyID = ""
    ds.AccessionNumber = ""

    # Серия и оборудование.
    ds.Modality = "SR"
    ds.SeriesInstanceUID = _uid(report_id, "series")
    ds.SeriesNumber = 990
    ds.SeriesDescription = {"uz": "Xulosa (medviz)", "en": "Report (medviz)"}.get(data.language, "Заключение (medviz)")
    ds.Manufacturer = "medviz"

    # SR Document General.
    ds.InstanceNumber = 1
    ds.ContentDate, ds.ContentTime = when[:8], when[8:]
    ds.CompletionFlag = "COMPLETE"
    ds.VerificationFlag = "VERIFIED"
    observer = Dataset()
    observer.VerifyingObserverName = (data.finalized_by or "unknown").replace(" ", "^")
    observer.VerifyingOrganization = organization
    observer.VerificationDateTime = when
    observer.VerifyingObserverIdentificationCodeSequence = Sequence([])
    ds.VerifyingObserverSequence = Sequence([observer])
    ds.PerformedProcedureCodeSequence = Sequence([])
    ds.ReferencedPerformedProcedureStepSequence = Sequence([])

    # Содержание.
    ds.ValueType = "CONTAINER"
    ds.ConceptNameCodeSequence = Sequence([_code("18748-4", "LN", "Diagnostic imaging report")])
    ds.ContinuityOfContent = "SEPARATE"
    items = []
    for i, sentence in enumerate(data.sentences):
        item = Dataset()
        item.RelationshipType = "CONTAINS"
        item.ValueType = "TEXT"
        item.ConceptNameCodeSequence = Sequence([_code("121071", "DCM", "Finding")])
        item.TextValue = sentence
        finding_id = data.sentence_map.get(str(i))
        if finding_id:
            item.ObservationUID = "2.25." + str(int(finding_id.replace("-", ""), 16))
        items.append(item)
    ds.ContentSequence = Sequence(items)
    return ds


def sr_bytes(ds) -> bytes:
    """Сериализация SR в файл DICOM (Part 10)."""
    import io

    from pydicom.filewriter import dcmwrite

    buf = io.BytesIO()
    dcmwrite(buf, ds, enforce_file_format=True)
    return buf.getvalue()
