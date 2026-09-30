"""Построение 3D-моделей из подтверждённых масок (ТЗ, FR-5).

Последовательность: marching cubes → сглаживание Таубина → ограничение числа граней;
экспорт glTF (GLB) для веба и STL для печати. Геометрия — numpy + scikit-image, без VTK.
Строится в воркере (`workers/mesh_tasks.py`) из мультиметочной маски сегментации.

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


def taubin_smooth(verts, faces, iterations: int = 10, lam: float = 0.5, mu: float = -0.53):
    """Сглаживание Таубина: убирает «ступеньки» вокселей без усадки объёма (в отличие от Лапласа)."""
    import numpy as np

    v = np.asarray(verts, dtype=np.float64).copy()
    f = np.asarray(faces, dtype=np.int64)
    edges = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    a, b = edges[:, 0], edges[:, 1]
    degree = np.bincount(np.concatenate([a, b]), minlength=len(v)).astype(np.float64)
    degree[degree == 0] = 1.0

    def step(x, factor):
        acc = np.zeros_like(x)
        np.add.at(acc, a, x[b])
        np.add.at(acc, b, x[a])
        return x + factor * (acc / degree[:, None] - x)

    for _ in range(iterations):
        v = step(step(v, lam), mu)
    return v


def mask_to_mesh(mask, affine, *, max_faces: int = 200_000, smooth_iterations: int = 10):
    """Бинарная маска (i, j, k) + аффинная матрица NIfTI → вершины (мм, RAS) и треугольники.

    marching cubes (scikit-image) → сглаживание Таубина → ограничение числа граней
    (упрощение за счёт шага marching cubes: 1, 2, 3… вокселя, пока граней не станет ≤ max_faces).
    Детерминированно при одинаковой маске (FR-6).
    """
    import numpy as np
    from skimage.measure import marching_cubes

    m = np.pad(np.asarray(mask, dtype=np.uint8), 1)  # замкнутая поверхность у края поля обзора
    if not m.any():
        raise ValueError("Маска пуста — строить нечего")
    step = 1
    while True:
        verts, faces, _, _ = marching_cubes(m.astype(np.float32), level=0.5, step_size=step,
                                            allow_degenerate=False)
        if len(faces) <= max_faces or step >= 8:
            break
        step += 1
    verts = verts - 1.0  # компенсация паддинга
    if smooth_iterations:
        verts = taubin_smooth(verts, faces, iterations=smooth_iterations)
    homog = np.concatenate([verts, np.ones((len(verts), 1))], axis=1)
    world = (homog @ np.asarray(affine, dtype=np.float64).T)[:, :3]
    if np.linalg.det(np.asarray(affine)[:3, :3]) < 0:
        faces = faces[:, ::-1]  # зеркальная матрица меняет ориентацию нормалей
    return world.astype(np.float32), np.ascontiguousarray(faces, dtype=np.uint32), step


def mesh_stats(verts, faces) -> dict:
    """Площадь поверхности и объём замкнутого меша (мм², мл) — для проверки против объёма маски."""
    import numpy as np

    v = np.asarray(verts, dtype=np.float64)
    tri = v[np.asarray(faces)]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = float(np.linalg.norm(cross, axis=1).sum() / 2)
    volume = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6)
    return {"vertices": int(len(v)), "faces": int(len(tri)), "surface_mm2": round(area, 1),
            "volume_ml": round(abs(volume) / 1000.0, 2)}


def _normals(verts, faces):
    import numpy as np

    v = np.asarray(verts, dtype=np.float64)
    tri = v[faces]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    vn = np.zeros_like(v)
    for k in range(3):
        np.add.at(vn, faces[:, k], fn)
    norm = np.linalg.norm(vn, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return fn, (vn / norm).astype(np.float32)


def to_stl(verts, faces, header: str = "medviz FR-5 mesh") -> bytes:
    """Бинарный STL (для 3D-печати), единицы — миллиметры."""
    import numpy as np

    faces = np.asarray(faces, dtype=np.int64)
    fn, _ = _normals(verts, faces)
    n = np.linalg.norm(fn, axis=1, keepdims=True)
    n[n == 0] = 1.0
    rec = np.zeros(len(faces), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    rec["n"] = fn / n
    rec["v"] = np.asarray(verts, dtype=np.float32)[faces]
    head = header.encode("ascii", "replace")[:80].ljust(80, b" ")
    return head + np.uint32(len(faces)).tobytes() + rec.tobytes()


def to_glb(verts, faces, name: str = "structure") -> bytes:
    """glTF 2.0 (GLB) для просмотра в браузере. Координаты переведены в метры (единица glTF),
    ось Z пациента (к голове) — вверх (ось Y glTF)."""
    import json
    import struct

    import numpy as np

    faces = np.asarray(faces, dtype=np.uint32)
    v = np.asarray(verts, dtype=np.float64) / 1000.0
    v = np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1).astype(np.float32)  # RAS → Y-up
    _, vn = _normals(v, faces.astype(np.int64))
    pos, nrm, idx = v.tobytes(), vn.tobytes(), faces.reshape(-1).tobytes()
    blob = pos + nrm + idx
    blob += b"\x00" * (-len(blob) % 4)
    doc = {
        "asset": {"version": "2.0", "generator": "medviz"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2,
                                                  "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.85, 0.55, 0.5, 1.0],
                                                "metallicFactor": 0.0, "roughnessFactor": 0.8},
                       "doubleSided": True}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos), "byteLength": len(nrm), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos) + len(nrm), "byteLength": len(idx), "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(v), "type": "VEC3",
             "min": v.min(axis=0).tolist(), "max": v.max(axis=0).tolist()},
            {"bufferView": 1, "componentType": 5126, "count": len(v), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5125, "count": int(faces.size), "type": "SCALAR"},
        ],
    }
    js = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body
