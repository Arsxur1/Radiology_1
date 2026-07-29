"""Оркестрация сегментации и порождения находок (ТЗ, FR-3, FR-6, SR-5, SR-7).

Поток:
  1. Гейт применимости (SR-7): вне диапазона — явный отказ, результат НЕ пишется.
  2. Инференс через адаптер модели.
  3. Детерминированные измерения по воксельной статистике (FR-6).
  4. Запись inference_result (полная трассировка SR-5) и findings
     (source=model, status=pending — «модель посчитала», НЕ подтверждено).

Находки создаются всегда, когда серия допущена, независимо от режима работы.
Видимость врачу определяется режимом (раздел 2) на уровне выдачи (routes),
а не на уровне записи: в SHADOW результаты копятся в БД, но не показываются.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.imaging import Series, Study
from app.models.ml import (
    ConfirmationStatus,
    Finding,
    FindingSource,
    InferenceResult,
    ModelVersion,
)
from app.services.applicability import SeriesContext, check_applicability
from app.services.inference_adapters import SegmentationModel
from app.services.measurements import VoxelSpacing, linear_size_mm, volume_ml
from app.services.structure_catalog import structure_by_key


class ApplicabilityRefused(Exception):
    """Серия вне границ применимости — отказ по SR-7."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class SegmentationOutcome:
    inference_result_id: uuid.UUID
    finding_ids: list[uuid.UUID]
    structure_count: int


def _series_context(series: Series, study: Study, age_years: float | None) -> SeriesContext:
    body_part = None
    if study.protocol and "chest" in study.protocol.lower():
        body_part = "CHEST"
    return SeriesContext(
        modality=series.modality,
        body_part=body_part,
        slice_thickness_mm=series.slice_thickness_mm,
        manufacturer=study.manufacturer,
        lossy_compressed=series.lossy_compressed,
        contrast_agent=series.contrast_agent,
        patient_age_years=age_years,
    )


def _spacing(series: Series) -> VoxelSpacing:
    vs = series.voxel_spacing or []
    x = vs[0] if len(vs) > 0 and vs[0] else 1.0
    y = vs[1] if len(vs) > 1 and vs[1] else 1.0
    z = vs[2] if len(vs) > 2 and vs[2] else (series.slice_thickness_mm or 1.0)
    return VoxelSpacing(float(x), float(y), float(z))


def _compute_measurements(structure_result, spacing: VoxelSpacing) -> dict:
    """Детерминированные измерения по одной структуре (FR-6)."""
    catalog = structure_by_key(structure_result.key)
    wanted = catalog.default_measurements if catalog else ("volume_ml",)
    out: dict = {}
    if "volume_ml" in wanted:
        out["volume_ml"] = volume_ml(structure_result.voxel_count, spacing)
    if "linear_size_mm" in wanted and structure_result.extent_voxels:
        ex, ey, ez = structure_result.extent_voxels
        out["linear_size_mm"] = {
            "x": linear_size_mm(ex, spacing.x_mm),
            "y": linear_size_mm(ey, spacing.y_mm),
            "z": linear_size_mm(ez, spacing.z_mm),
        }
    return out


def segment_series(
    db: Session,
    *,
    series: Series,
    model_version: ModelVersion,
    model: SegmentationModel,
    age_years: float | None = None,
) -> SegmentationOutcome:
    """Сегментировать серию и породить находки. Отказ по SR-7 при выходе за границы."""
    study = db.get(Study, series.study_id)

    # 1. Гейт применимости (SR-7).
    decision = check_applicability(
        _series_context(series, study, age_years), model_version.applicability
    )
    if not decision.admitted:
        raise ApplicabilityRefused(decision.reasons)

    # 2. Инференс.
    spacing = _spacing(series)
    output = model.infer(
        series.object_prefix or series.series_instance_uid,
        (spacing.x_mm, spacing.y_mm, spacing.z_mm),
    )

    # 3. Трассируемый результат (SR-5).
    inference = InferenceResult(
        series_id=series.id,
        model_version_id=model_version.id,
        artifact_ref=output.mask_artifact_ref,
        preprocessing_params=output.preprocessing_params,
        metrics=output.extra_metrics,
    )
    db.add(inference)
    db.flush()

    # 4. Находки: source=model, статус pending (не подтверждено врачом).
    finding_ids: list[uuid.UUID] = []
    for sr in output.structures:
        catalog = structure_by_key(sr.key)
        finding = Finding(
            series_id=series.id,
            inference_result_id=inference.id,
            coding_system="RadLex",
            code=catalog.radlex_code if catalog else None,
            label=catalog.label_ru if catalog else sr.key,
            measurements=_compute_measurements(sr, spacing),
            coordinates={"structure_key": sr.key},
            source=FindingSource.MODEL,
            confirmation_status=ConfirmationStatus.PENDING,
        )
        db.add(finding)
        db.flush()
        finding_ids.append(finding.id)

    return SegmentationOutcome(
        inference_result_id=inference.id,
        finding_ids=finding_ids,
        structure_count=len(finding_ids),
    )
