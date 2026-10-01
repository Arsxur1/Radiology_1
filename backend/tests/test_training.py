"""Тесты офлайн-контура обучения на синтетических мини-датасетах.

Структура файлов повторяет официальные релизы MIMIC-CXR-JPG и VinDr-(P)CXR;
реальные данные не используются.
"""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pytest

from app.training.cli import main
from app.training.contour import ContourError, require_training_contour
from app.training.label_map import map_labels, normalize, validate_map
from app.training.manifest import ManifestRecord, label_stats, read_jsonl, write_jsonl
from app.training.metrics import auroc, mean_defined
from app.training.model_card import (
    CardError,
    build_applicability,
    build_card,
    registration_payload,
    weights_sha256,
)
from app.training.sources import parse_mimic_cxr_jpg, parse_vindr
from app.training.splits import (
    FrozenTestError,
    freeze_test_set,
    load_frozen,
    training_records,
)

CHEXPERT = [
    "Atelectasis", "Cardiomegaly", "Consolidation", "Edema", "Enlarged Cardiomediastinum",
    "Fracture", "Lung Lesion", "Lung Opacity", "No Finding", "Pleural Effusion",
    "Pleural Other", "Pneumonia", "Pneumothorax", "Support Devices",
]


def _write_csv(path: Path, header: list[str], rows: list[list], gz: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if gz else open
    with opener(path, "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


# ─── Контур ───────────────────────────────────────────────────────────────────
def test_training_forbidden_outside_training_contour():
    for env in ({}, {"MEDVIZ_CONTOUR": "production"}, {"MEDVIZ_CONTOUR": "research"}):
        with pytest.raises(ContourError):
            require_training_contour(env)
    require_training_contour({"MEDVIZ_CONTOUR": "training"})


def test_cli_refuses_data_commands_on_production(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEDVIZ_CONTOUR", "production")
    code = main(["manifest", "--dataset", "vindr-cxr", "--root", str(tmp_path), "--out", str(tmp_path / "m.jsonl")])
    assert code == 2
    assert "Обучение запрещено" in capsys.readouterr().err


# ─── Метки ────────────────────────────────────────────────────────────────────
def test_label_map_codes_exist_in_vocabulary():
    assert validate_map() == []


def test_chexpert_labels_mapped_and_diagnosis_excluded():
    report = map_labels(CHEXPERT)
    assert report.mapped["Pleural Effusion"] == "CXR-200"
    assert report.mapped["No Finding"] == "CXR-000"
    assert "Pneumonia" in report.excluded_diagnoses       # диагноз — не учим (SR-1)
    assert report.unmapped == []


def test_vindr_labels_normalized():
    assert normalize(" Nodule/Mass ") == "nodule mass"
    report = map_labels(["Nodule/Mass", "Tuberculosis", "Other lesion", "Something new"])
    assert report.mapped["Nodule/Mass"] == "CXR-112"
    assert report.excluded_diagnoses == ["Tuberculosis"]
    assert report.excluded_vague == ["Other lesion"]
    assert report.unmapped == ["Something new"]       # не угадываем — эксперту


# ─── MIMIC-CXR-JPG ────────────────────────────────────────────────────────────
@pytest.fixture
def mimic_root(tmp_path) -> Path:
    root = tmp_path / "mimic"
    labels = {c: "" for c in CHEXPERT}
    s1 = {**labels, "Pleural Effusion": "1.0", "Cardiomegaly": "-1.0", "Pneumonia": "1.0"}
    s2 = {**labels, "No Finding": "1.0"}
    _write_csv(root / "mimic-cxr-2.0.0-chexpert.csv.gz", ["subject_id", "study_id", *CHEXPERT], [
        ["10000032", "50000001", *[s1[c] for c in CHEXPERT]],
        ["10000099", "50000002", *[s2[c] for c in CHEXPERT]],
    ], gz=True)
    _write_csv(root / "mimic-cxr-2.0.0-split.csv.gz", ["dicom_id", "study_id", "subject_id", "split"], [
        ["img-pa", "50000001", "10000032", "train"],
        ["img-lat", "50000001", "10000032", "train"],
        ["img-2", "50000002", "10000099", "test"],
    ], gz=True)
    _write_csv(root / "mimic-cxr-2.0.0-metadata.csv.gz", ["dicom_id", "ViewPosition"], [
        ["img-pa", "PA"], ["img-lat", "LATERAL"], ["img-2", "AP"],
    ], gz=True)
    return root


def test_mimic_parsing(mimic_root):
    records, report = parse_mimic_cxr_jpg(mimic_root)
    ids = {r.image_id: r for r in records}
    assert set(ids) == {"img-pa", "img-2"}                  # боковая проекция отброшена
    pa = ids["img-pa"]
    assert pa.image_path == "files/p10/p10000032/s50000001/img-pa.jpg"
    assert pa.labels["CXR-200"] == 1                        # выпот
    assert pa.labels["CXR-500"] is None                     # неопределённость → маска
    assert pa.labels["CXR-201"] == 0                        # пусто → 0
    assert "CXR-pneumonia" not in pa.labels and "Pneumonia" in report.excluded_diagnoses
    assert ids["img-2"].split == "test" and ids["img-2"].population == "adult"


# ─── VinDr-CXR / VinDr-PCXR ───────────────────────────────────────────────────
@pytest.fixture
def vindr_root(tmp_path) -> Path:
    root = tmp_path / "vindr"
    cols = ["image_id", "rad_id", "Cardiomegaly", "Pleural effusion", "Tuberculosis", "No finding"]
    _write_csv(root / "annotations/image_labels_train.csv", cols, [
        ["a1", "R1", 1, 0, 1, 0], ["a1", "R2", 1, 1, 0, 0], ["a1", "R3", 0, 0, 0, 1],
        ["a2", "R1", 0, 0, 0, 1], ["a2", "R2", 0, 0, 0, 1], ["a2", "R3", 0, 0, 0, 1],
    ])
    _write_csv(root / "annotations/image_labels_test.csv", [c for c in cols if c != "rad_id"], [
        ["t1", 0, 1, 0, 0],
    ])
    _write_csv(root / "annotations/annotations_train.csv",
               ["image_id", "rad_id", "class_name", "x_min", "y_min", "x_max", "y_max"], [
        ["a1", "R1", "Cardiomegaly", 10, 20, 110, 220],
        ["a2", "R1", "No finding", "", "", "", ""],
    ])
    return root


def test_vindr_majority_and_boxes(vindr_root):
    records, report = parse_vindr(vindr_root, "vindr-cxr")
    ids = {r.image_id: r for r in records}
    a1 = ids["a1"]
    assert a1.labels["CXR-500"] == 1        # 2 из 3 врачей
    assert a1.labels["CXR-200"] == 0        # 1 из 3 — не большинство
    assert a1.image_path == "train/a1.dicom"
    assert a1.boxes[0]["code"] == "CXR-500" and a1.boxes[0]["x_max"] == 110.0
    assert ids["t1"].split == "test" and ids["t1"].labels["CXR-200"] == 1
    assert "Tuberculosis" in report.excluded_diagnoses
    assert all(r.split in ("train", "validate", "test") for r in records)


def test_vindr_pediatric_population(vindr_root):
    records, _ = parse_vindr(vindr_root, "vindr-pcxr")
    assert {r.population for r in records} == {"pediatric"}


# ─── Замороженный тест ────────────────────────────────────────────────────────
def _rec(image_id, split, patient):
    return ManifestRecord("vindr-cxr", image_id, f"x/{image_id}", patient, split, "adult", {"CXR-500": 1})


def test_freeze_and_disjointness(tmp_path):
    recs = [_rec("t1", "test", "p1"), _rec("a1", "train", "p2"), _rec("a2", "train", "p1"),
            _rec("v1", "validate", "p3")]
    path = tmp_path / "frozen.json"
    frozen = freeze_test_set(recs, path)
    with pytest.raises(FrozenTestError):
        freeze_test_set(recs, path)          # повторно сформировать нельзя
    assert load_frozen(path).digest == frozen.digest
    kept, leaked = training_records(recs, frozen)
    assert {r.image_id for r in kept} == {"a1", "v1"}
    assert leaked == 1                       # a2 — пациент теста, исключён


def test_frozen_tamper_detected(tmp_path):
    path = tmp_path / "frozen.json"
    freeze_test_set([_rec("t1", "test", "p1")], path)
    data = json.loads(path.read_text("utf-8"))
    data["image_ids"].append("vindr-cxr:extra")
    path.write_text(json.dumps(data), "utf-8")
    with pytest.raises(FrozenTestError):
        load_frozen(path)


# ─── Метрики ──────────────────────────────────────────────────────────────────
def test_auroc():
    assert auroc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert auroc([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]) == 0.0
    assert auroc([0, 1], [0.5, 0.5]) == 0.5              # связь
    assert auroc([0, None, 1], [0.1, 0.99, 0.9]) == 1.0   # маска игнорируется
    assert auroc([1, 1], [0.1, 0.2]) is None              # один класс
    assert mean_defined({"a": 1.0, "b": None, "c": 0.5}) == 0.75


# ─── Карточка модели ──────────────────────────────────────────────────────────
def test_applicability_by_population():
    adult = build_applicability("adult")
    assert adult["age"] == {"min_years": 18} and adult["allow_lossy"] is False
    with pytest.raises(CardError):
        build_applicability("pediatric")                  # возраст детей — только явно
    kids = build_applicability("pediatric", age_max=10)
    assert kids["age"] == {"min_years": 0, "max_years": 10}


def test_card_and_registration(tmp_path):
    w = tmp_path / "model.pt"
    w.write_bytes(b"weights")
    card = build_card(
        name="cxr_findings_adult", semver="0.1.0", weights_hash=weights_sha256(w),
        population="adult", applicability=build_applicability("adult"), codes=["CXR-200"],
        datasets=["mimic-cxr-jpg"], excluded_labels=["Pneumonia"], metrics={}, frozen_digest="d",
    )
    assert card["initial_status"] == "shadow"
    reg = registration_payload(card)
    assert set(reg) == {"name", "semver", "weights_hash", "applicability", "task", "operating_points",
                        "training_data"}
    assert reg["training_data"] == card["datasets"]          # происхождение данных идёт в гейт
    assert reg["task"] == "classification" and reg["operating_points"] == {}


def test_youden_threshold():
    from app.training.thresholds import operating_points, youden_threshold

    op = youden_threshold([0, 0, 1, 1, None], [0.1, 0.3, 0.6, 0.9, 0.99])
    assert op["threshold"] == 0.6 and op["sensitivity"] == 1.0 and op["specificity"] == 1.0
    assert youden_threshold([1, 1], [0.2, 0.9]) is None          # один класс — нет точки
    ops = operating_points(["A", "B"], [[1, 0], [0, 0]], [[0.8, 0.1], [0.2, 0.3]])
    assert set(ops) == {"A"}                                      # у B нет позитивов


def test_cli_import_site(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDVIZ_CONTOUR", "training")
    good = {"dataset": "ncmc", "image_id": "s1", "image_path": "p/s1", "patient_key": "u1",
            "split": "train", "population": "pediatric", "labels": {"CXR-200": 1, "CXR-XXX": 1, "CXR-000": 0},
            "view": None, "boxes": []}
    data = {"report": {"records": 3}, "records": [good, {**good, "dataset": "mimic-cxr-jpg"}, {"junk": 1}]}
    src = tmp_path / "export.json"
    src.write_text(json.dumps(data), "utf-8")
    out = tmp_path / "work/ncmc.jsonl"
    assert main(["import-site", "--json", str(src), "--out", str(out)]) == 0
    recs = read_jsonl(out)
    assert len(recs) == 1 and recs[0].labels == {"CXR-200": 1, "CXR-000": 0}
    report = json.loads(out.with_suffix(".report.json").read_text("utf-8"))
    assert report["bad_records"] == 2 and report["unknown_codes"] == ["CXR-XXX"]


# ─── Сквозной CLI: манифест → заморозка ───────────────────────────────────────
def test_cli_manifest_and_freeze(vindr_root, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEDVIZ_CONTOUR", "training")
    out = tmp_path / "work/vindr.jsonl"
    assert main(["manifest", "--dataset", "vindr-cxr", "--root", str(vindr_root), "--out", str(out)]) == 0
    report = json.loads(out.with_suffix(".report.json").read_text("utf-8"))
    assert report["records"] == 3 and "Tuberculosis" in report["excluded_diagnoses"]
    assert label_stats(read_jsonl(out))["CXR-500"]["pos"] == 1
    capsys.readouterr()
    assert main(["freeze", "--manifest", str(out), "--out", str(tmp_path / "work/frozen.json")]) == 0
    assert json.loads(capsys.readouterr().out)["images"] == 1


def test_manifest_roundtrip(tmp_path):
    recs = [_rec("a1", "train", "p1")]
    write_jsonl(recs, tmp_path / "m.jsonl")
    assert read_jsonl(tmp_path / "m.jsonl")[0].labels == {"CXR-500": 1}
