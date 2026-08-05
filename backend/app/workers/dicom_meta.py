"""Извлечение метаданных из обезличенного DICOM для зеркалирования в БД."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_dicom_age(value: str | None) -> float | None:
    """Разобрать DICOM PatientAge (формат nnnD/W/M/Y) в годы.

    Примеры: "045Y" → 45.0, "018M" → 1.5, "030W" → ~0.577, "007D" → ~0.019.
    Возраст нужен для границ применимости (SR-7): взрослые/дети раздельно.
    """
    if not value:
        return None
    value = str(value).strip().upper()
    unit = value[-1] if value[-1:] in ("D", "W", "M", "Y") else "Y"
    digits = value[:-1] if value[-1:] in ("D", "W", "M", "Y") else value
    try:
        n = float(digits)
    except ValueError:
        return None
    factor = {"Y": 1.0, "M": 1 / 12.0, "W": 1 / 52.0, "D": 1 / 365.0}[unit]
    return round(n * factor, 3)


def extract_study_meta(tags: dict) -> dict:
    return {
        "study_instance_uid": tags.get("StudyInstanceUID"),
        "modality": tags.get("Modality", "OT"),
        "study_date": _parse_date(tags.get("StudyDate")),
        "description": tags.get("StudyDescription"),
        "manufacturer": tags.get("Manufacturer"),
        "manufacturer_model": tags.get("ManufacturerModelName"),
        "software_version": tags.get("SoftwareVersions"),
        "protocol": tags.get("ProtocolName"),
        "patient_age_years": parse_dicom_age(tags.get("PatientAge")),
    }


def extract_series_meta(tags: dict) -> dict:
    pixel_spacing = tags.get("PixelSpacing")
    spacing = None
    if pixel_spacing:
        parts = pixel_spacing if isinstance(pixel_spacing, list) else str(pixel_spacing).split("\\")
        try:
            spacing = [float(parts[0]), float(parts[1]), _to_float(tags.get("SpacingBetweenSlices"))]
        except (ValueError, IndexError):
            spacing = None

    transfer_syntax = tags.get("TransferSyntaxUID", "")
    # Список lossy transfer syntaxes (JPEG lossy, JPEG-LS lossy, JPEG2000 lossy).
    lossy_uids = {"1.2.840.10008.1.2.4.50", "1.2.840.10008.1.2.4.51", "1.2.840.10008.1.2.4.81"}

    return {
        "series_instance_uid": tags.get("SeriesInstanceUID"),
        "series_number": int(tags["SeriesNumber"]) if tags.get("SeriesNumber") else None,
        "modality": tags.get("Modality", "OT"),
        "description": tags.get("SeriesDescription"),
        "slice_thickness_mm": _to_float(tags.get("SliceThickness")),
        "voxel_spacing": spacing,
        "transfer_syntax": transfer_syntax or None,
        "lossy_compressed": transfer_syntax in lossy_uids,
        "contrast_agent": bool(tags.get("ContrastBolusAgent")),
    }
