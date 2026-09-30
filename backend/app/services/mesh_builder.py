"""3D-модель структуры по подтверждённой находке сегментации (FR-5).

Гейт проверяется синхронно в API (врач сразу видит причину отказа), геометрия
строится в воркере (`workers/mesh_tasks.py`): там есть nibabel и scikit-image.

Строится только то, что врач принял как есть:
  - находка модели подтверждена врачом (SR-2) и не из теневого прогона;
  - врач не исправлял её — иначе маска модели не совпадает с принятым результатом;
  - шаг маски по любой оси и толщина среза не больше порога (иначе — «ступеньки»);
  - серия без сжатия с потерями.
Состояние хранится в `finding.coordinates["mesh"]`: queued → ready | failed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imaging import Series
from app.models.ml import ConfirmationStatus, Correction, CorrectionType, Finding, FindingSource
from app.services.mesh import MeshGateDecision, can_build_mesh


@dataclass
class MeshSource:
    finding: Finding
    series: Series
    structure_key: str
    label_ids: list[int]
    mask_ref: str


class MeshRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def mesh_source(db: Session, finding_id: uuid.UUID) -> MeshSource:
    """Проверить гейт FR-5 для находки. MeshRefused — с причиной для врача; LookupError — нет находки."""
    f = db.get(Finding, finding_id)
    if f is None:
        raise LookupError("Находка не найдена")
    inference = f.inference_result
    if f.source != FindingSource.MODEL or inference is None:
        raise MeshRefused("3D-модель строится только по маске сегментации модели")
    if inference.shadow_run:
        raise LookupError("Находка не найдена")  # теневой прогон не раскрываем
    key = (f.coordinates or {}).get("structure_key")
    if not key:
        raise MeshRefused("У находки нет маски структуры (не результат сегментации)")
    modified = db.execute(
        select(Correction.id).where(Correction.finding_id == f.id,
                                    Correction.correction_type == CorrectionType.MODIFIED).limit(1)
    ).first()
    if modified:
        raise MeshRefused("Врач исправил находку — маска модели не совпадает с принятым результатом")
    series = db.get(Series, f.series_id)
    params = inference.preprocessing_params or {}
    mask_spacing = [float(v) for v in params.get("mask_spacing_mm") or []]
    thickness = series.slice_thickness_mm if series else None
    # Геометрию определяет самая грубая ось: толщина среза или шаг маски (быстрый режим — 3 мм).
    effective = max([v for v in [thickness, *mask_spacing] if v], default=None)
    decision: MeshGateDecision = can_build_mesh(
        slice_thickness_mm=effective,
        lossy_compressed=bool(series.lossy_compressed) if series else False,
        mask_confirmed=f.confirmation_status == ConfirmationStatus.CONFIRMED,
    )
    if not decision.allowed:
        raise MeshRefused(decision.reason or "Построение недопустимо")
    ids = (params.get("label_ids") or {}).get(key)
    if not inference.artifact_ref or not ids:
        raise MeshRefused("Маска сегментации недоступна (демо-модель или старый результат)")
    return MeshSource(f, series, key, [int(i) for i in ids], inference.artifact_ref)


def set_mesh_state(f: Finding, state: dict) -> None:
    # JSONB-поле переприсваивается целиком, чтобы SQLAlchemy увидел изменение.
    f.coordinates = {**(f.coordinates or {}), "mesh": state}


def build_and_store(db: Session, finding_id: uuid.UUID, *, load_mask, store) -> dict:
    """Построить STL и GLB и сохранить. load_mask(ref) -> bytes (NIfTI.gz); store(key, data, type) -> ref."""
    import gzip

    import nibabel as nib
    import numpy as np

    from app.services.mesh import mask_to_mesh, mesh_stats, to_glb, to_stl

    src = mesh_source(db, finding_id)  # гейт повторяется: за время очереди находка могла измениться
    img = nib.Nifti1Image.from_bytes(gzip.decompress(load_mask(src.mask_ref)))
    mask = np.isin(np.asarray(img.dataobj), src.label_ids)
    verts, faces, step = mask_to_mesh(mask, img.affine)
    stats = mesh_stats(verts, faces)
    base = f"{src.series.object_prefix or src.series.series_instance_uid}/mesh/{src.finding.id}"
    state = {
        "status": "ready",
        "structure_key": src.structure_key,
        "stl": store(f"{base}.stl", to_stl(verts, faces), "model/stl"),
        "glb": store(f"{base}.glb", to_glb(verts, faces, name=src.structure_key), "model/gltf-binary"),
        "marching_cubes_step": step,
        **stats,
    }
    set_mesh_state(src.finding, state)
    return state
