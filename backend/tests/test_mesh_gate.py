"""Тесты гейта построения 3D-модели (ТЗ, FR-5)."""

from app.services.mesh import can_build_mesh


def _ok(**over):
    base = dict(slice_thickness_mm=1.0, lossy_compressed=False, mask_confirmed=True)
    base.update(over)
    return base


def test_allows_good_mask():
    assert can_build_mesh(**_ok()).allowed is True


def test_refuses_unconfirmed_mask():
    # Строим только из подтверждённых масок (FR-5).
    d = can_build_mesh(**_ok(mask_confirmed=False))
    assert d.allowed is False
    assert "подтвержд" in d.reason


def test_refuses_thick_slices():
    # Отказ с причиной, а не модель с артефактами (FR-5).
    d = can_build_mesh(**_ok(slice_thickness_mm=5.0))
    assert d.allowed is False
    assert "Толщина среза" in d.reason


def test_refuses_unknown_thickness():
    assert can_build_mesh(**_ok(slice_thickness_mm=None)).allowed is False


def test_refuses_lossy():
    assert can_build_mesh(**_ok(lossy_compressed=True)).allowed is False
