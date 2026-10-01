"""Логика проверки на детском наборе Guangzhou: метки по путям и агрегаты (без модели)."""

from __future__ import annotations

from app.training.pediatric_eval import find_images, label_of, normal_floor_thresholds, npz_images, summarize


def test_labels_from_paths(tmp_path):
    assert label_of("chest_xray/test/NORMAL/IM-0001-0001.jpeg") == ("normal", 0)
    assert label_of("chest_xray/test/PNEUMONIA/person1_bacteria_1.jpeg") == ("bacterial", 1)
    assert label_of("chest_xray/test/PNEUMONIA/person2_virus_6.jpeg") == ("viral", 1)
    assert label_of("chest_xray/test/OTHER/x.jpeg") is None
    for rel in ("chest_xray/test/NORMAL/a.jpeg", "chest_xray/train/NORMAL/b.jpeg",
                "chest_xray/test/PNEUMONIA/p_virus_1.jpeg", "chest_xray/test/NORMAL/notes.txt"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    found = find_images(tmp_path, ("test",))
    assert [(p.name, k) for p, k, _ in found] == [("a.jpeg", "normal"), ("p_virus_1.jpeg", "viral")]


def test_summary_metrics():
    th = {"CXR-100": 0.5, "CXR-200": 0.6}
    rec = [
        {"kind": "normal", "y": 0, "probs": {"CXR-100": 0.1, "CXR-200": 0.2}, "raw_pneumonia": 0.1},
        {"kind": "normal", "y": 0, "probs": {"CXR-100": 0.55, "CXR-200": 0.1}, "raw_pneumonia": 0.2},
        {"kind": "bacterial", "y": 1, "probs": {"CXR-100": 0.9, "CXR-200": 0.7}, "raw_pneumonia": 0.9},
        {"kind": "viral", "y": 1, "probs": {"CXR-100": 0.4, "CXR-200": 0.3}, "raw_pneumonia": 0.8},
    ]
    s = summarize(rec, th, bootstrap=200)
    assert s["n"] == {"normal": 2, "bacterial": 1, "viral": 1, "total": 4}
    # Оценка «есть что-то» = максимум по кодам: 0.2, 0.55 | 0.9, 0.4 → 3 из 4 пар упорядочены верно.
    assert s["any_finding_auroc"] == 0.75
    lo, hi = s["any_finding_auroc_ci95"]
    assert 0 <= lo <= 0.75 <= hi <= 1
    assert s["normal_with_any_draft"] == 0.5 and s["normal_mean_drafts"] == 0.5
    assert s["pneumonia_with_any_draft"] == 0.5
    assert s["bacterial_with_any_draft"] == 1.0 and s["viral_with_any_draft"] == 0.0
    assert s["per_code"]["CXR-200"]["draft_rate_normal"] == 0.0
    assert s["per_code"]["CXR-200"]["draft_rate_pneumonia"] == 0.5
    assert s["reference_raw_pneumonia_output_auroc"] == 1.0
    assert summarize(rec, th, bootstrap=200) == s                      # детерминированно


def test_npz_version(tmp_path):
    import numpy as np

    np.savez(tmp_path / "p.npz", test_images=np.zeros((3, 4, 4), "uint8"),
             test_labels=np.array([[0], [1], [1]], "uint8"))
    got = npz_images(tmp_path / "p.npz", ("test",))
    assert [(k, y) for _, k, y in got] == [("normal", 0), ("pneumonia", 1), ("pneumonia", 1)]
    assert got[0][0].dtype == "float32" and got[0][0].shape == (4, 4)


def test_hwcmc_layout(tmp_path):
    for rel in ("Pediatric Pneumonia/normal/normal_1.png", "Pediatric Pneumonia/mycoplasma/mycoplasma_1.png",
                "Pediatric Pneumonia/mixed/mixed_2.png", "Pediatric Pneumonia/virus/virus_3.png"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    got = sorted((k, y) for _, k, y in find_images(tmp_path, ()))
    assert got == [("mixed", 1), ("mycoplasma", 1), ("normal", 0), ("viral", 1)]


def test_normal_floor_never_lowers_and_caps_false_drafts():
    normals = [{"y": 0, "probs": {"A": s / 100, "B": 0.1}} for s in range(100)]   # A: 0.00…0.99
    th = normal_floor_thresholds(normals + [{"y": 1, "probs": {"A": 1.0, "B": 1.0}}], {"A": 0.5, "B": 0.55}, 0.05)
    assert th["B"] == 0.55                                   # здоровые ниже порога — не трогаем
    assert 0.95 < th["A"] <= 0.96                            # не больше 5% здоровых выше порога
    assert sum(r["probs"]["A"] >= th["A"] for r in normals) <= 5
