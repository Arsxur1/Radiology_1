"""Парсеры публичных датасетов рентгена грудной клетки → единый манифест.

Поддерживаются (структура каталогов — как в официальных релизах на PhysioNet):
- MIMIC-CXR-JPG: CheXpert-метки на уровне исследования, официальный сплит,
  метаданные проекций; взрослые.
- VinDr-CXR: метки нескольких врачей на изображение + рамки находок; взрослые.
- VinDr-PCXR: та же схема, педиатрия.

Метки читаются из заголовков CSV (а не из жёсткого списка), поэтому новые или
переименованные метки не теряются — они попадают в отчёт как несопоставленные.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from app.training.label_map import MappingReport, map_labels
from app.training.manifest import ADULT, PEDIATRIC, ManifestRecord, combine

FRONTAL_VIEWS = frozenset({"PA", "AP"})


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    title: str
    population: str
    license_note: str


DATASETS: dict[str, DatasetSpec] = {
    "mimic-cxr-jpg": DatasetSpec(
        "mimic-cxr-jpg", "MIMIC-CXR-JPG", ADULT,
        "PhysioNet Credentialed Health Data License; личный доступ + DUA",
    ),
    "vindr-cxr": DatasetSpec(
        "vindr-cxr", "VinDr-CXR", ADULT,
        "PhysioNet credentialed; личный доступ + DUA",
    ),
    "vindr-pcxr": DatasetSpec(
        "vindr-pcxr", "VinDr-PCXR", PEDIATRIC,
        "PhysioNet credentialed; личный доступ + DUA",
    ),
}


class SourceError(Exception):
    """Не найдены файлы датасета или нарушена их структура."""


# ─── Общие утилиты ────────────────────────────────────────────────────────────
def _find(root: Path, candidates: list[str]) -> Path:
    for rel in candidates:
        p = root / rel
        if p.exists():
            return p
    raise SourceError(f"Не найден ни один из файлов {candidates} в {root}")


def read_csv(path: Path) -> Iterator[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


def csv_header(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


def _hash_split(key: str, validate_fraction: float) -> str:
    """Детерминированное отнесение ключа пациента к train/validate (без утечки)."""
    bucket = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "validate" if bucket < validate_fraction else "train"


def _codes_from(report: MappingReport, raw_values: dict[str, int | None]) -> dict[str, int | None]:
    grouped: dict[str, list[int | None]] = defaultdict(list)
    for raw, code in report.mapped.items():
        grouped[code].append(raw_values.get(raw))
    return {code: combine(vals) for code, vals in grouped.items()}


# ─── MIMIC-CXR-JPG ────────────────────────────────────────────────────────────
def _chexpert_value(raw: str, uncertain_as: int | None, blank_as: int | None) -> int | None:
    raw = (raw or "").strip()
    if raw == "":
        return blank_as
    value = float(raw)
    if value == 1.0:
        return 1
    if value == 0.0:
        return 0
    return uncertain_as  # -1.0 — неопределённость (по умолчанию маскируется)


def parse_mimic_cxr_jpg(
    root: Path,
    *,
    frontal_only: bool = True,
    uncertain_as: int | None = None,
    blank_as: int | None = 0,
) -> tuple[list[ManifestRecord], MappingReport]:
    chexpert = _find(root, ["mimic-cxr-2.0.0-chexpert.csv.gz", "mimic-cxr-2.0.0-chexpert.csv"])
    split_f = _find(root, ["mimic-cxr-2.0.0-split.csv.gz", "mimic-cxr-2.0.0-split.csv"])
    meta_f = _find(root, ["mimic-cxr-2.0.0-metadata.csv.gz", "mimic-cxr-2.0.0-metadata.csv"])

    label_cols = [c for c in csv_header(chexpert) if c not in ("subject_id", "study_id")]
    report = map_labels(label_cols)

    study_labels: dict[str, dict[str, int | None]] = {}
    for row in read_csv(chexpert):
        raw = {c: _chexpert_value(row.get(c, ""), uncertain_as, blank_as) for c in label_cols}
        study_labels[row["study_id"]] = _codes_from(report, raw)

    views = {row["dicom_id"]: (row.get("ViewPosition") or "").strip().upper()
             for row in read_csv(meta_f)}

    records: list[ManifestRecord] = []
    for row in read_csv(split_f):
        dicom_id, study_id, subject_id = row["dicom_id"], row["study_id"], row["subject_id"]
        view = views.get(dicom_id) or None
        if frontal_only and view not in FRONTAL_VIEWS:
            continue
        labels = study_labels.get(study_id)
        if labels is None:
            continue  # у исследования нет меток
        split = row["split"].strip().lower()
        records.append(ManifestRecord(
            dataset="mimic-cxr-jpg",
            image_id=dicom_id,
            image_path=f"files/p{subject_id[:2]}/p{subject_id}/s{study_id}/{dicom_id}.jpg",
            patient_key=f"mimic:{subject_id}",
            split="validate" if split == "validate" else split,
            population=ADULT,
            labels=labels,
            view=view,
        ))
    return records, report


# ─── VinDr-CXR / VinDr-PCXR ───────────────────────────────────────────────────
def _aggregate_readers(values: list[int], policy: str) -> int:
    if policy == "any":
        return int(any(values))
    return int(sum(values) / len(values) >= 0.5)  # большинство врачей


def parse_vindr(
    root: Path,
    dataset: str,
    *,
    reader_policy: str = "majority",
    validate_fraction: float = 0.1,
) -> tuple[list[ManifestRecord], MappingReport]:
    spec = DATASETS[dataset]
    records: list[ManifestRecord] = []
    report: MappingReport | None = None

    for part in ("train", "test"):
        labels_f = _find(root, [f"annotations/image_labels_{part}.csv", f"image_labels_{part}.csv"])
        header = csv_header(labels_f)
        label_cols = [c for c in header if c not in ("image_id", "rad_id")]
        part_report = map_labels(label_cols)
        report = report or part_report
        # Метки нового раздела, отсутствующие в первом, тоже учитываются в отчёте.
        for raw, code in part_report.mapped.items():
            report.mapped.setdefault(raw, code)
        for bucket in ("excluded_diagnoses", "excluded_vague", "unmapped"):
            target = getattr(report, bucket)
            target.extend(x for x in getattr(part_report, bucket) if x not in target)

        per_image: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in read_csv(labels_f):
            per_image[row["image_id"]].append(row)

        boxes: dict[str, list[dict]] = defaultdict(list)
        try:
            ann_f = _find(root, [f"annotations/annotations_{part}.csv", f"annotations_{part}.csv"])
            for row in read_csv(ann_f):
                code = part_report.mapped.get(row.get("class_name", ""))
                if code and (row.get("x_min") or "").strip():
                    boxes[row["image_id"]].append({
                        "code": code,
                        "reader": row.get("rad_id") or None,
                        "x_min": float(row["x_min"]), "y_min": float(row["y_min"]),
                        "x_max": float(row["x_max"]), "y_max": float(row["y_max"]),
                    })
        except SourceError:
            pass  # рамки необязательны для классификации

        for image_id, rows in per_image.items():
            raw = {
                c: _aggregate_readers([int(float(r.get(c) or 0)) for r in rows], reader_policy)
                for c in label_cols
            }
            split = "test" if part == "test" else _hash_split(image_id, validate_fraction)
            records.append(ManifestRecord(
                dataset=dataset,
                image_id=image_id,
                image_path=f"{part}/{image_id}.dicom",
                patient_key=f"{dataset}:{image_id}",  # ID пациента в релизе не раскрыт
                split=split,
                population=spec.population,
                labels=_codes_from(part_report, raw),
                boxes=boxes.get(image_id, []),
            ))

    assert report is not None
    return records, report


def parse_dataset(dataset: str, root: Path, **kwargs) -> tuple[list[ManifestRecord], MappingReport]:
    if dataset not in DATASETS:
        raise SourceError(f"Неизвестный датасет {dataset!r}; доступны: {sorted(DATASETS)}")
    if dataset == "mimic-cxr-jpg":
        return parse_mimic_cxr_jpg(root, **kwargs)
    return parse_vindr(root, dataset, **kwargs)
