"""Тесты извлечения метаданных серии (ТЗ, раздел 5: пригодность к 3D)."""

from app.workers.dicom_meta import extract_series_meta, extract_study_meta


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
        }
    )
    assert meta["modality"] == "CT"
    assert meta["manufacturer"] == "Siemens"
    assert meta["study_date"].year == 2026
