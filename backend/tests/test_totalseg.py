"""Сегментация КТ: статистика по мультиметочной маске, отпечаток весов, прогон ACTIVE+SHADOW."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.models.ml import Finding, InferenceResult, ModelStatus, ModelVersion
from app.services.inference_adapters import weights_fingerprint
from app.services.model_registry import PromotionError, register_candidate

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_integration_flow import _make_series  # noqa: E402

from app.workers.segmentation_tasks import segment_with_all  # noqa: E402


def test_labelmap_structures_groups_and_extent():
    np = pytest.importorskip("numpy")
    from app.services.inference_adapters import labelmap_structures

    names = {1: "liver", 2: "vertebrae_T1", 3: "vertebrae_T2", 4: "spleen"}
    lm = np.zeros((10, 10, 10), dtype=np.uint8)
    lm[0:2, 0:3, 0:4] = 1          # печень 24 вокселя, bbox 2×3×4
    lm[5, 5, 5] = 2
    lm[6, 5, 5] = 3                # T1+T2 → грудные позвонки
    out = {s.key: s for s in labelmap_structures(lm, names, ["liver", "vertebrae_thoracic", "spleen", "heart"])}
    assert out["liver"].voxel_count == 24 and out["liver"].extent_voxels == (2, 3, 4)
    assert out["vertebrae_thoracic"].voxel_count == 2
    assert "spleen" not in out and "heart" not in out   # не в поле обзора / нет класса — не находка


def test_weights_fingerprint_changes_with_content(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "w.pth").write_bytes(b"1")
    h1 = weights_fingerprint(tmp_path)
    (tmp_path / "a" / "w.pth").write_bytes(b"2")
    assert weights_fingerprint(tmp_path) != h1


def test_adapter_validation(db):
    kw = dict(name="ts", semver="2.0.0", weights_hash="h", applicability={}, actor="a")
    mv = register_candidate(db, task="segmentation", adapter={"type": "totalsegmentator", "task": "total"}, **kw)
    assert mv.status == ModelStatus.SHADOW
    with pytest.raises(PromotionError):
        register_candidate(db, task="classification", adapter={"type": "totalsegmentator"}, **kw)
    with pytest.raises(PromotionError):
        register_candidate(db, task="segmentation",
                           adapter={"type": "totalsegmentator", "task": "brain_structures"}, **kw)


def test_active_and_shadow_segmentation(db):
    _, _, series = _make_series(db)
    app_ = {"modality": ["CT"], "body_part": ["CHEST"], "age": {"min_years": 18}}
    for status, h in ((ModelStatus.ACTIVE, "demo-a"), (ModelStatus.SHADOW, "demo-b"), (ModelStatus.SHADOW, "real")):
        db.add(ModelVersion(name=h, semver="1", weights_hash=h, applicability=app_, status=status, task="segmentation"))
    series.study.patient_age_years = 45.0
    db.flush()
    res = {r["model"]: r for r in segment_with_all(db, series)["results"]}
    assert res["demo-a@1"]["shadow"] is False and res["demo-b@1"]["shadow"] is True
    assert "error" in res["real@1"]                          # настоящие веса не подменяются заглушкой
    shadow = db.query(InferenceResult).filter_by(shadow_run=True).count()
    assert shadow == 1 and db.query(Finding).count() > 0
