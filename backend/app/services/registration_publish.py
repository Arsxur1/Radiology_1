"""Совмещённая серия в просмотрщике (FR-4, FR-2).

После того как врач подтвердил качество совмещения, совмещаемую серию (например, МРТ)
пересчитывают на сетку опорной (например, КТ) по сохранённому преобразованию и
публикуют в обезличенный Orthanc как новую серию опорного исследования: та же система
координат (FrameOfReferenceUID), та же геометрия срезов. OHIF показывает их рядом с
синхронной прокруткой и позволяет накладывать.

Серия производная и помечена так: ImageType DERIVED, описание «совмещено, подтверждено
врачом». UID детерминированы от совмещения — повторная публикация заменяет ту же серию.
Публикуется только подтверждённое совмещение: неподтверждённое не должно выглядеть
как готовый результат.
"""

from __future__ import annotations


def _uid(*parts: str) -> str:
    from pydicom.uid import generate_uid

    return generate_uid(entropy_srcs=["medviz-reg", *parts])


def resampled_series(fixed, moving, transform, template, *, registration_id: str, modality: str,
                     description: str) -> list:
    """Серия DICOM: moving, пересчитанная на сетку fixed. Возвращает список pydicom Dataset.

    fixed, moving — изображения SimpleITK; transform — точки fixed → moving;
    template — любой обезличенный срез опорной серии (атрибуты пациента и исследования).
    """
    import numpy as np
    import SimpleITK as sitk
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    background = float(sitk.GetArrayViewFromImage(moving).min())
    res = sitk.Resample(moving, fixed, transform, sitk.sitkLinear, background, sitk.sitkFloat32)
    arr = sitk.GetArrayFromImage(res)                           # (z, y, x)
    lo, hi = float(np.percentile(arr, 1)), float(np.percentile(arr, 99))
    pixels = np.clip(np.rint(arr), -32768, 32767).astype(np.int16)
    direction = np.array(fixed.GetDirection()).reshape(3, 3)
    row_dir, col_dir = direction[:, 0], direction[:, 1]
    sx, sy, sz = fixed.GetSpacing()

    series_uid = _uid(registration_id, "series")
    frame_of_reference = str(getattr(template, "FrameOfReferenceUID", "")) or _uid(registration_id, "for")
    sop_class = "1.2.840.10008.5.1.4.1.1.4" if modality == "MR" else "1.2.840.10008.5.1.4.1.1.2"
    out = []
    for k in range(pixels.shape[0]):
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.file_meta.MediaStorageSOPClassUID = sop_class
        ds.SOPClassUID = sop_class
        ds.SOPInstanceUID = _uid(registration_id, "instance", str(k))
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        ds.SpecificCharacterSet = "ISO_IR 192"
        # Пациент и исследование — как у опорной серии (уже обезличены).
        for kw in ("PatientName", "PatientID", "PatientBirthDate", "PatientSex", "PatientAge",
                   "StudyInstanceUID", "StudyDate", "StudyTime", "StudyID", "AccessionNumber",
                   "ReferringPhysicianName", "StudyDescription"):
            setattr(ds, kw, getattr(template, kw, ""))
        ds.Modality = modality
        ds.SeriesInstanceUID = series_uid
        ds.SeriesNumber = 980
        ds.SeriesDescription = description[:64]
        ds.ImageType = ["DERIVED", "SECONDARY", "REGISTERED"]
        ds.FrameOfReferenceUID = frame_of_reference
        ds.Manufacturer = "medviz"
        ds.InstanceNumber = k + 1
        origin = fixed.TransformIndexToPhysicalPoint((0, 0, k))
        ds.ImagePositionPatient = [f"{v:.4f}" for v in origin]
        ds.ImageOrientationPatient = [f"{v:.6f}" for v in (*row_dir, *col_dir)]
        ds.PixelSpacing = [f"{sy:.4f}", f"{sx:.4f}"]            # строки, столбцы
        ds.SliceThickness = f"{sz:.4f}"
        ds.Rows, ds.Columns = int(pixels.shape[1]), int(pixels.shape[2])
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
        ds.RescaleIntercept, ds.RescaleSlope = "0", "1"
        ds.WindowCenter, ds.WindowWidth = f"{(lo + hi) / 2:.1f}", f"{max(hi - lo, 1.0):.1f}"
        ds.PixelData = pixels[k].tobytes()
        out.append(ds)
    return out


def dataset_bytes(ds) -> bytes:
    import io

    from pydicom.filewriter import dcmwrite

    buf = io.BytesIO()
    dcmwrite(buf, ds, enforce_file_format=True)
    return buf.getvalue()
