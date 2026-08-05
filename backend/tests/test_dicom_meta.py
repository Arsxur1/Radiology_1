"""Тесты извлечения метаданных серии (ТЗ, раздел 5: пригодность к 3D)."""

from app.workers.dicom_meta import extract_series_meta, extract_study_meta, parse_dicom_age


def test_lossy_detection():
    meta = extract_series_meta(
        {
            "SeriesInstanceUID": "1.2.3",
            "Modality": "CT",
            "SliceThickness": "1.0",
            "TransferSyntaxUID": "1.2.840.10008.1.2.4.50",  # JPEG lossy
        }
    )
    assert meta["lossy_compressed"] is True
    assert meta["slice_thickness_mm"] == 1.0


def test_lossless_not_flagged():
    meta = extract_series_meta(
        {
            "SeriesInstanceUID": "1.2.3",
            "Modality": "CT",
            "SliceThickness": "0.625",
            "TransferSyntaxUID": "1.2.840.10008.1.2.1",  # explicit VR little endian
        }
    )
    assert meta["lossy_compressed"] is False


def test_study_meta_parsing():
    meta = extract_study_meta(
        {
            "StudyInstanceUID": "1.2.3",
            "Modality": "CT",
            "StudyDate": "20260101",
            "Manufacturer": "Siemens",
            "PatientAge": "045Y",
        }
    )
    assert meta["modality"] == "CT"
    assert meta["manufacturer"] == "Siemens"
    assert meta["study_date"].year == 2026
    assert meta["patient_age_years"] == 45.0


def test_parse_dicom_age():
    assert parse_dicom_age("045Y") == 45.0
    assert parse_dicom_age("018M") == round(18 / 12.0, 3)  # младенец ~1.5 года
    assert parse_dicom_age("030W") == round(30 / 52.0, 3)
    assert parse_dicom_age("007D") == round(7 / 365.0, 3)
    assert parse_dicom_age("50") == 50.0  # без суффикса — трактуем как годы
    assert parse_dicom_age(None) is None
    assert parse_dicom_age("") is None
