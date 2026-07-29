"""Запуск сегментации серии (ТЗ, FR-3). Отказ по SR-7 возвращается явно.

На этапе 2 без GPU используется детерминированная заглушка; реальный адаптер
TotalSegmentator подключается на стенде. В обоих случаях результаты идут в
контур правок (FR-9) и учитывают режим работы при показе (раздел 2).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.imaging import Series
from app.models.ml import ModelStatus, ModelVersion
from app.services import segmentation
from app.services.inference_adapters import StubSegmentationModel
from app.services.segmentation import ApplicabilityRefused
from app.services.structure_catalog import structures_for_region

router = APIRouter(prefix="/segmentation", tags=["segmentation"])


class SegmentRequest(BaseModel):
    series_id: uuid.UUID
    model_version_id: uuid.UUID
    age_years: float | None = None
    # Для этапа 2 без GPU: использовать детерминированную заглушку.
    use_stub: bool = True


class SegmentResponse(BaseModel):
    inference_result_id: uuid.UUID
    finding_ids: list[uuid.UUID]
    structure_count: int


@router.post("", response_model=SegmentResponse)
def run_segmentation(
    req: SegmentRequest,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RESEARCHER, Role.RADIOLOGIST)),
) -> SegmentResponse:
    series = db.get(Series, req.series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    model_version = db.get(ModelVersion, req.model_version_id)
    if model_version is None:
        raise HTTPException(status_code=404, detail="Версия модели не найдена")
    if model_version.status == ModelStatus.RETIRED:
        raise HTTPException(status_code=409, detail="Версия модели выведена из эксплуатации")

    if req.use_stub:
        keys = [s.key for s in structures_for_region("CHEST")]
        model = StubSegmentationModel(keys, weights_hash=model_version.weights_hash)
    else:  # pragma: no cover
        from app.services.inference_adapters import TotalSegmentatorAdapter

        model = TotalSegmentatorAdapter(weights_hash=model_version.weights_hash)

    try:
        outcome = segmentation.segment_series(
            db, series=series, model_version=model_version, model=model,
            age_years=req.age_years,
        )
        db.commit()
    except ApplicabilityRefused as e:
        # SR-7: явный отказ с причиной, а не результат «с пониженной уверенностью».
        raise HTTPException(
            status_code=422,
            detail={"refused": True, "reasons": e.reasons},
        ) from e

    return SegmentResponse(
        inference_result_id=outcome.inference_result_id,
        finding_ids=outcome.finding_ids,
        structure_count=outcome.structure_count,
    )
