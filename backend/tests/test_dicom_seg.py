"""DICOM SEG: перенос маски на сетку среза и публикация только видимых результатов."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.ml import InferenceResult, ModelStatus, ModelVersion
from app.services import segmentation
from app.services.inference_adapters import SegmentationModel, SegmentationOutput, StructureResult

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_integration_flow import _make_series  # noqa: E402


def test_resample_to_slice_handles_lps_orientation():
    np = pytest.importorskip("numpy")
    from app.services.dicom_seg import resample_to_slice

    lm = np.zeros((4, 4, 2), dtype=np.uint8)
    lm[3, 0, 1] = 7                                    # воксель RAS (i=3, j=0, k=1)
    affine = np.diag([1.0, 1.0, 2.0, 1.0])             # 1×1×2 мм, начало в (0,0,0)
    # Срез z=2 мм; столбцы идут к левой стороне пациента (−R), строки — назад (−A).
    ds = SimpleNamespace(Rows=4, Columns=4, ImagePositionPatient=[-3.0, -3.0, 2.0],
                         ImageOrientationPatient=[1, 0, 0, 0, 1, 0], PixelSpacing=[1.0, 1.0])
    out = resample_to_slice(lm, affine, ds)
    # LPS(−3+c, −3+r) → RAS(3−c, 3−r): вокселю i=3,j=0 соответствует c=0, r=3.
    assert out[3, 0] == 7 and int((out > 0).sum()) == 1


class SegModel(SegmentationModel):
    weights_hash = "demo-seg"

    def infer(self, prefix, spacing):
        return SegmentationOutput(mask_artifact_ref=None, seg_dicom=b"SEG",
                                  structures=[StructureResult(key="heart", voxel_count=1000)])


@pytest.mark.parametrize("status,published", [(ModelStatus.ACTIVE, True), (ModelStatus.SHADOW, False)])
def test_seg_published_only_when_visible(db, status, published):
    _, study, series = _make_series(db)
    mv = ModelVersion(name="s", semver="1", weights_hash="demo-seg", status=status, task="segmentation",
                      applicability={"modality": ["CT"], "body_part": ["CHEST"], "age": {"min_years": 18}})
    db.add(mv)
    db.flush()
    sent = []
    out = segmentation.segment_series(db, series=series, model_version=mv, model=SegModel(), age_years=45,
                                      publish_seg=lambda b: sent.append(b) or {"orthanc_id": "x"})
    ir = db.get(InferenceResult, out.inference_result_id)
    assert bool(sent) is published and ("dicom_seg" in ir.metrics) is published
