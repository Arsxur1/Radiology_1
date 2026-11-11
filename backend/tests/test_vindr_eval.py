"""Проверка модели на детских находках (VinDr-PCXR): метрики по находкам и формат отчёта."""

from __future__ import annotations

import json

from app.training.vindr_eval import NORMAL_CODE, summarize_findings

TH = {"CXR-200": 0.5, "CXR-500": 0.5}       # модель умеет: выпот, кардиомегалия


def rec(labels, probs, age=5.0):
    return {"labels": labels, "probs": probs, "age": age}


def dataset():
    out = []
    # 12 детей с выпотом: у 9 модель уверена, у 3 — пропуск.
    for i in range(12):
        out.append(rec({"CXR-200": 1, "CXR-500": 0, NORMAL_CODE: 0}, {"CXR-200": 0.9 if i < 9 else 0.2}))
    # 20 здоровых: у 2 модель ошибочно рисует выпот.
    for i in range(20):
        out.append(rec({"CXR-200": 0, "CXR-500": 0, NORMAL_CODE: 1}, {"CXR-200": 0.7 if i < 2 else 0.1},
                       age=0.5 if i < 10 else 8.0))
    # 3 ребёнка с находкой, которой у модели нет (интерстициальное затемнение).
    for _ in range(3):
        out.append(rec({"CXR-106": 1, "CXR-200": 0, NORMAL_CODE: 0}, {"CXR-200": 0.1}, age=None))
    return out


def test_per_finding_metrics_and_normals():
    s = summarize_findings(dataset(), TH, bootstrap=0)
    assert s["n"] == {"total": 35, "normal": 20, "abnormal": 15}
    e = s["per_code"]["CXR-200"]
    assert e["positives"] == 12 and e["evaluated"] and e["auroc"] is not None
    assert e["sensitivity"] == 0.75 and e["ppv"] == round(9 / 11, 4)
    assert e["draft_rate_normal"] == 0.1
    assert s["normal_with_any_draft"] == 0.1
    # Кардиомегалии в наборе нет — по отдельности не оценивается.
    assert s["per_code"]["CXR-500"]["evaluated"] is False and s["per_code"]["CXR-500"]["auroc"] is None


def test_findings_model_cannot_detect_are_listed():
    s = summarize_findings(dataset(), TH, bootstrap=0)
    assert s["not_covered_by_model"] == {"CXR-106": 3}
    assert s["abnormal_with_any_draft"] == round(9 / 15, 4)


def test_age_groups():
    s = summarize_findings(dataset(), TH, bootstrap=0)
    g = s["by_age_group"]
    assert g["0–1 год"]["n"] == 10 and g["возраст неизвестен"]["n"] == 3
    assert g["0–1 год"]["normal_with_any_draft"] == 0.2      # обе ошибки — у младенцев
    assert g["5–12 лет"]["normal_with_any_draft"] == 0.0


def test_report_has_only_aggregates():
    """Соглашение PhysioNet: наружу — только сводные цифры (ни снимков, ни идентификаторов)."""
    s = summarize_findings(dataset(), TH, bootstrap=50)
    text = json.dumps(s, ensure_ascii=False)
    assert "probs" not in text and "labels" not in text and "image" not in text
    assert s["any_finding_auroc_ci95"] is not None


def test_normal_code_matches_platform():
    from app.services.classification import NORMAL_CODE as platform_normal
    from app.training.label_map import map_labels

    assert NORMAL_CODE == platform_normal
    assert map_labels(["No finding"]).mapped.get("No finding") == NORMAL_CODE


def _synthetic_release(root):
    """Мини-релиз в формате VinDr-PCXR: CSV меток и DICOM-шум (не данные пациентов)."""
    import csv

    import numpy as np
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    labels = [("t1", 0, 1, 0), ("t2", 1, 0, 0), ("t3", 0, 0, 1)]   # выпот, кардиомегалия, норма
    (root / "annotations").mkdir(parents=True)
    for part, rows in (("test", labels), ("train", [("a1", 0, 0, 1)])):
        with open(root / f"annotations/image_labels_{part}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "Cardiomegaly", "Pleural effusion", "No finding"])
            w.writerows(rows)
        (root / part).mkdir()
        for image_id, *_ in rows:
            d = Dataset()
            d.file_meta = FileMetaDataset()
            d.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            d.file_meta.MediaStorageSOPClassUID = d.SOPClassUID = "1.2.840.10008.5.1.4.1.1.1"
            d.file_meta.MediaStorageSOPInstanceUID = d.SOPInstanceUID = generate_uid()
            d.PatientAge = "004Y" if image_id != "t3" else "008M"
            d.PhotometricInterpretation = "MONOCHROME1" if image_id == "t2" else "MONOCHROME2"
            d.Rows = d.Columns = 32
            d.SamplesPerPixel, d.BitsAllocated, d.BitsStored, d.HighBit, d.PixelRepresentation = 1, 16, 12, 11, 0
            d.PixelData = np.random.default_rng(1).integers(0, 4000, (32, 32)).astype(np.uint16).tobytes()
            d.save_as(root / part / f"{image_id}.dicom", enforce_file_format=True)


def test_collect_records_reads_release_like_the_platform(tmp_path):
    from app.training.sources import parse_vindr
    from app.training.vindr_eval import collect_records

    _synthetic_release(tmp_path)
    manifest, _ = parse_vindr(tmp_path, "vindr-pcxr")
    seen = []

    def score(arr):
        seen.append(arr.shape)
        return {"CXR-200": 0.9, "CXR-500": 0.1}

    recs = collect_records(tmp_path, manifest, score)               # по умолчанию — только тест
    assert len(recs) == 3 and seen == [(32, 32)] * 3
    ages = sorted(r["age"] for r in recs)
    assert abs(ages[0] - 8 / 12) < 0.01 and ages[-1] == 4.0          # 8 месяцев и 4 года из PatientAge
    by_label = {tuple(sorted(r["labels"].items())): r for r in recs}
    assert len(by_label) == 3 and all("image_id" not in r for r in recs)
    s = summarize_findings(recs, TH, bootstrap=0, min_positives=1)
    assert s["n"] == {"total": 3, "normal": 1, "abnormal": 2}
    assert s["normal_with_any_draft"] == 1.0                        # модель-заглушка рисует выпот всем
