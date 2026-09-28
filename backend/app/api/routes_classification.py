"""Запуск классификации находок ОГК по серии (FR-10, SR-1, SR-7).

Отказ по границам применимости возвращается явно (422). Модель в SHADOW
допускается: результат пишется как теневой и врачу не показывается.
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
from app.services import classification
from app.services.classification import ModelUnavailable, WrongModelTask
from app.services.segmentation import ApplicabilityRefused

router = APIRouter(prefix="/classification", tags=["classification"])


class ClassifyRequest(BaseModel):
    series_id: uuid.UUID
    model_version_id: uuid.UUID
    age_years: float | None = None


class ClassifyResponse(BaseModel):
    inference_result_id: uuid.UUID
    finding_ids: list[uuid.UUID]
    shadow_run: bool


@router.post("", response_model=ClassifyResponse)
def run_classification(
    req: ClassifyRequest,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN, Role.RESEARCHER, Role.RADIOLOGIST)),
) -> ClassifyResponse:
    series = db.get(Series, req.series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    mv = db.get(ModelVersion, req.model_version_id)
    if mv is None:
        raise HTTPException(status_code=404, detail="Версия модели не найдена")
    if mv.status == ModelStatus.RETIRED:
        raise HTTPException(status_code=409, detail="Версия модели выведена из эксплуатации")

    try:
        model = classification.load_model(mv)
    except ModelUnavailable as e:
        raise HTTPException(status_code=503, detail=f"Модель недоступна: {e}") from e

    try:
        out = classification.classify_series(
            db, series=series, model_version=mv, model=model, age_years=req.age_years,
        )
        db.commit()
    except WrongModelTask as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ApplicabilityRefused as e:
        raise HTTPException(status_code=422, detail={"refused": True, "reasons": e.reasons}) from e
    return ClassifyResponse(
        inference_result_id=out.inference_result_id, finding_ids=out.finding_ids, shadow_run=out.shadow_run,
    )
