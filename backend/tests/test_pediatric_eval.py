"""Логика проверки на детском наборе Guangzhou: метки по путям и агрегаты (без модели)."""

from __future__ import annotations

from app.training.pediatric_eval import find_images, label_of, summarize


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
