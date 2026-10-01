"""Кириллица и узбекский текст в DICOM: от аппарата до обезличенной копии (SR-9, FR-1)."""

from __future__ import annotations

import io

import pydicom
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from app.services.anonymization import anonymize_dataset
from app.services.dicom_charset import normalize_charset

DESC = "Рентгенография ОГК"
NAME = "Алиев^Жасур"
UZ_DESC = "Ko'krak qafasi rentgenografiyasi"
UZ_CYR = "Кўкрак қафаси, ўғил бола, ҳолат"   # ў қ ғ ҳ — нет в ISO_IR 144


def _dicom(charset, desc: bytes, name: bytes, *, series_desc: bytes | None = None) -> bytes:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.1"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.Modality, ds.PatientID = "DX", "MRN-1"
    if charset:
        ds.SpecificCharacterSet = charset
    ds.StudyDescription, ds.PatientName = "x", "x"
    ds[0x00081030].value = desc          # сырые байты — как их прислал аппарат
    ds[0x00100010].value = name
    if series_desc is not None:
        ds.SeriesDescription = "x"
        ds[0x0008103E].value = series_desc
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def _ingest(raw: bytes, fallback: str = "cp1251"):
    """Как в ingest.process_raw_instance: прочитать, нормализовать, обезличить, записать."""
    ds = pydicom.dcmread(io.BytesIO(raw))
    guessed = normalize_charset(ds, fallback)
    clean, plan = anonymize_dataset(ds)
    buf = io.BytesIO()
    clean.save_as(buf, enforce_file_format=True)
    return guessed, plan, pydicom.dcmread(io.BytesIO(buf.getvalue()))


@pytest.mark.parametrize("charset,desc,name,guess", [
    ("ISO_IR 192", f"{DESC} / Ko'krak qafasi", NAME, None),
    ("ISO_IR 192", UZ_CYR, NAME, None),
    ("ISO_IR 144", DESC, NAME, None),
    (None, DESC, NAME, "utf-8"),            # UTF-8 без объявления
    (None, UZ_CYR, NAME, "utf-8"),
    (None, DESC, NAME, "cp1251"),           # Windows-1251 без объявления
    (None, UZ_DESC, "Aliyev^Jasur", None),  # латиница — угадывать нечего
])
def test_text_survives_ingest(charset, desc, name, guess):
    codec = {"ISO_IR 192": "utf-8", "ISO_IR 144": "iso8859_5", None: guess or "ascii"}[charset]
    guessed, plan, clean = _ingest(_dicom(charset, desc.encode(codec), name.encode(codec)))
    assert guessed == guess
    assert str(clean.StudyDescription) == desc          # врач видит описание как есть
    assert plan.real_name == name                        # ФИО — в идентифицирующий контур верно
    assert clean.SpecificCharacterSet == "ISO_IR 192"    # обезличенная копия — всегда UTF-8
    assert "?" not in str(clean.StudyDescription)


def test_iso2022_cyrillic_multi_charset():
    raw = _dicom(["", "ISO 2022 IR 144"], b"Chest \x1b-L" + DESC.encode("iso8859_5"),
                 b"Aliev^Jasur=\x1b-L" + "Алиев^Жасур".encode("iso8859_5"))
    _, plan, clean = _ingest(raw)
    assert str(clean.StudyDescription) == f"Chest {DESC}"
    assert "Алиев" in plan.real_name


def test_fallback_is_configurable_and_all_fields_consistent():
    text = "Грудь"
    raw = _dicom(None, text.encode("koi8_r"), b"ANON", series_desc=text.encode("koi8_r"))
    guessed, _, clean = _ingest(raw, fallback="koi8_r")
    assert guessed == "koi8-r"
    assert str(clean.StudyDescription) == text and str(clean.SeriesDescription) == text


def test_ascii_untouched():
    guessed, plan, clean = _ingest(_dicom(None, b"CHEST PA", b"DOE^JOHN"))
    assert guessed is None and plan.real_name == "DOE^JOHN"
    assert str(clean.StudyDescription) == "CHEST PA"
