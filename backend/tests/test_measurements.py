"""Тесты детерминированных измерений (ТЗ, FR-6: воспроизводимость)."""

from app.services.inference_adapters import StubSegmentationModel
from app.services.measurements import (
    VoxelSpacing,
    density_stats,
    linear_size_mm,
    ratio,
    volume_ml,
)


def test_volume_ml_known_value():
    # 1 000 000 вокселей по 1 мм³ = 1 000 000 мм³ = 1000 мл.
    spacing = VoxelSpacing(1.0, 1.0, 1.0)
    assert volume_ml(1_000_000, spacing) == 1000.0


def test_volume_scales_with_spacing():
    assert volume_ml(1000, VoxelSpacing(2.0, 2.0, 2.0)) == volume_ml(8000, VoxelSpacing(1.0, 1.0, 1.0))


def test_volume_reproducible():
    spacing = VoxelSpacing(0.7, 0.7, 1.5)
    assert volume_ml(123456, spacing) == volume_ml(123456, spacing)


def test_linear_size():
    assert linear_size_mm(50, 0.7) == 35.0


def test_density_stats_deterministic():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    a = density_stats(values)
    b = density_stats(list(reversed(values)))  # порядок входа не влияет
    assert a == b
    assert a["mean"] == 30.0
    assert a["min"] == 10.0
    assert a["max"] == 50.0


def test_density_empty():
    assert density_stats([]) == {"count": 0}


def test_ratio():
    assert ratio(1.0, 4.0) == 0.25
    assert ratio(1.0, 0.0) is None


def test_stub_model_deterministic():
    # FR-6: та же серия той же версией → тот же результат.
    m1 = StubSegmentationModel(["heart", "aorta"])
    m2 = StubSegmentationModel(["heart", "aorta"])
    out1 = m1.infer("series-prefix-x", (1.0, 1.0, 1.0))
    out2 = m2.infer("series-prefix-x", (1.0, 1.0, 1.0))
    counts1 = [s.voxel_count for s in out1.structures]
    counts2 = [s.voxel_count for s in out2.structures]
    assert counts1 == counts2
    # Разный вход → другой результат.
    out3 = m1.infer("series-prefix-y", (1.0, 1.0, 1.0))
    assert [s.voxel_count for s in out3.structures] != counts1
