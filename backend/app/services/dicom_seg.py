"""Маска сегментации → DICOM SEG для показа контуров в OHIF (FR-2, FR-3, SR-1).

Модель выдаёт мультиметочную маску в пространстве NIfTI. Чтобы врач видел, ЧТО именно
измерено, маска перекладывается на сетку каждого исходного DICOM-среза (через аффинную
матрицу, ближайший сосед — работает при любой ориентации) и упаковывается в стандартный
DICOM SEG, ссылающийся на обезличенные срезы. OHIF показывает его поверх снимка.

SEG помечается как черновик ИИ: алгоритм AUTOMATIC, описание серии «не подтверждено».
Строится только для результатов, видимых врачу (не для теневого прогона).
"""

from __future__ import annotations

from dataclasses import dataclass

SERIES_DESCRIPTION = "ИИ-черновик сегментации (не подтверждено врачом)"


@dataclass
class SegSegment:
    key: str          # структура каталога
    label: str        # подпись для врача
    ids: list[int]    # метки маски, входящие в структуру


def resample_to_slice(labelmap, affine, ds):
    """Метки маски (NIfTI, RAS) на пиксельной сетке одного DICOM-среза (LPS)."""
    import numpy as np

    rows, cols = int(ds.Rows), int(ds.Columns)
    ipp = np.array([float(v) for v in ds.ImagePositionPatient])
    iop = [float(v) for v in ds.ImageOrientationPatient]
    row_dir, col_dir = np.array(iop[:3]), np.array(iop[3:])   # рост индекса столбца / строки
    dr, dc = (float(v) for v in ds.PixelSpacing)               # между строками / столбцами
    i, j = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    lps = ipp + j[..., None] * dc * row_dir + i[..., None] * dr * col_dir
    ras = lps * np.array([-1.0, -1.0, 1.0])
    homog = np.concatenate([ras, np.ones((rows, cols, 1))], axis=-1)
    vox = homog @ np.linalg.inv(affine).T
    idx = np.rint(vox[..., :3]).astype(int)
    shape = np.array(labelmap.shape[:3])
    inside = np.all((idx >= 0) & (idx < shape), axis=-1)
    out = np.zeros((rows, cols), dtype=labelmap.dtype)
    ii = idx[inside]
    out[inside] = labelmap[ii[:, 0], ii[:, 1], ii[:, 2]]
    return out


# Атрибуты типа 2 (обязательны, могут быть пустыми), которые обезличивание удаляет.
_TYPE2_EMPTY = ("PatientName", "PatientID", "PatientBirthDate", "PatientSex", "StudyID",
                "AccessionNumber", "ReferringPhysicianName", "StudyDate", "StudyTime")


def _with_empty_type2(ds):
    """Копия среза с пустыми атрибутами типа 2 — PHI не возвращается, стандарт соблюдён."""
    import copy

    d = copy.deepcopy(ds)
    for kw in _TYPE2_EMPTY:
        if kw not in d:
            setattr(d, kw, "")
    return d


def build_seg(source_datasets: list, labelmap, affine, segments: list[SegSegment], *,
              algorithm: str, algorithm_version: str, manufacturer: str = "medviz"):  # pragma: no cover
    """DICOM SEG (binary) по исходным обезличенным срезам. Возвращает pydicom Dataset или None."""
    import highdicom as hd
    import numpy as np
    from pydicom.sr.codedict import codes

    srcs = sorted((_with_empty_type2(d) for d in source_datasets),
                  key=lambda d: int(getattr(d, "InstanceNumber", 0) or 0))
    per_slice = np.stack([resample_to_slice(labelmap, affine, d) for d in srcs])  # (n, rows, cols)
    present = [s for s in segments if np.isin(per_slice, s.ids).any()]
    if not present:
        return None
    mask = np.stack([np.isin(per_slice, s.ids) for s in present], axis=-1).astype(np.uint8)
    algo = hd.AlgorithmIdentificationSequence(
        name=algorithm, version=algorithm_version, family=codes.cid7162.ArtificialIntelligence,
    )
    descriptions = [
        hd.seg.SegmentDescription(
            segment_number=n,
            segment_label=s.label[:64],
            segmented_property_category=codes.SCT.Organ,
            segmented_property_type=codes.SCT.Organ,
            algorithm_type=hd.seg.SegmentAlgorithmTypeValues.AUTOMATIC,
            algorithm_identification=algo,
            tracking_uid=hd.UID(),
            tracking_id=s.key,
        )
        for n, s in enumerate(present, start=1)
    ]
    seg = hd.seg.Segmentation(
        source_images=srcs,
        pixel_array=mask,
        segmentation_type=hd.seg.SegmentationTypeValues.BINARY,
        segment_descriptions=descriptions,
        series_instance_uid=hd.UID(),
        series_number=900,
        sop_instance_uid=hd.UID(),
        instance_number=1,
        manufacturer=manufacturer,
        manufacturer_model_name="medviz",
        software_versions=algorithm_version,
        device_serial_number="medviz",
        series_description=SERIES_DESCRIPTION,
        omit_empty_frames=True,
    )
    # Подписи на русском: без явной кодировки UTF-8 они превращаются в «????».
    seg.SpecificCharacterSet = "ISO_IR 192"
    return seg
