"""Построение 3D-моделей из подтверждённых масок (ТЗ, FR-5).

Последовательность: marching cubes → сглаживание → дециматия; экспорт glTF
(Draco) для веба и STL для печати. Тяжёлая геометрия (VTK/trimesh) подключается
на стенде; здесь — гейт безопасности и контур.

Ключевое требование FR-5: при толщине среза, недостаточной для корректной
геометрии, система ОТКАЗЫВАЕТ в построении с указанием причины, а не строит
модель с артефактами. И строит только из ПОДТВЕРЖДЁННЫХ масок.
"""

from __future__ import annotations

from dataclasses import dataclass

# Порог по умолчанию: срезы толще этого дают ступенчатую геометрию.
# Точное значение согласуется под клиническую задачу.
DEFAULT_MAX_SLICE_THICKNESS_MM = 3.0


@dataclass
class MeshGateDecision:
    allowed: bool
    reason: str | None = None


def can_build_mesh(
    *,
    slice_thickness_mm: float | None,
    lossy_compressed: bool,
    mask_confirmed: bool,
    max_slice_thickness_mm: float = DEFAULT_MAX_SLICE_THICKNESS_MM,
) -> MeshGateDecision:
    """Гейт построения меша (FR-5). Чистая функция, тестируема без геометрии."""
    if not mask_confirmed:
        return MeshGateDecision(False, "Маска не подтверждена врачом — построение недопустимо")
    if slice_thickness_mm is None:
        return MeshGateDecision(False, "Неизвестна толщина среза — построение недопустимо")
    if slice_thickness_mm > max_slice_thickness_mm:
        return MeshGateDecision(
            False,
            f"Толщина среза {slice_thickness_mm} мм > допустимой {max_slice_thickness_mm} мм: "
            "геометрия будет с артефактами",
        )
    if lossy_compressed:
        return MeshGateDecision(False, "Серия сжата с потерями — геометрия ненадёжна")
    return MeshGateDecision(True)


def build_mesh(mask_ref: str, *, decision: MeshGateDecision):  # pragma: no cover
    """Построить меш (marching cubes → сглаживание → дециматия). Подключается на стенде."""
    if not decision.allowed:
        raise ValueError(f"Построение меша запрещено: {decision.reason}")
    raise NotImplementedError("VTK/trimesh подключаются на стенде; см. docs/STAGE-2.md")
