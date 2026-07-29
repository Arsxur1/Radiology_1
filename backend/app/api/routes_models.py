"""Реестр и жизненный цикл моделей (ТЗ, FR-10, PCCP).

Продвижение — осознанное действие ответственного лица (роль admin) при
пройденном гейте. Откат мгновенный. Никакого авто-обновления (SR-3).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.ml import ModelVersion
from app.services import model_registry
from app.services.model_registry import (
    PromotionCriteria,
    PromotionError,
    evaluate_promotion,
)

router = APIRouter(prefix="/models", tags=["models"])


class ModelOut(BaseModel):
    id: uuid.UUID
    name: str
    semver: str
    weights_hash: str
    status: str
    applicability: dict


class RegisterIn(BaseModel):
    name: str
    semver: str
    weights_hash: str
    applicability: dict = {}


class PromotionEvidenceIn(BaseModel):
    """Свидетельства для гейта продвижения (шаги 4–6)."""

    frozen_test_cases: int
    frozen_test_superior: bool
    shadow_rejection_rate: float | None
    no_regression_on_new_devices: bool


class PromoteIn(PromotionEvidenceIn):
    justification: str


class RollbackIn(BaseModel):
    reason: str


def _out(m: ModelVersion) -> ModelOut:
    return ModelOut(
        id=m.id, name=m.name, semver=m.semver, weights_hash=m.weights_hash,
        status=m.status.value, applicability=m.applicability,
    )


@router.get("", response_model=list[ModelOut])
def list_models(db: Session = Depends(get_db)) -> list[ModelOut]:
    rows = db.execute(select(ModelVersion)).scalars().all()
    return [_out(m) for m in rows]


@router.post("/candidates", response_model=ModelOut)
def register_candidate(
    payload: RegisterIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> ModelOut:
    m = model_registry.register_candidate(
        db, name=payload.name, semver=payload.semver, weights_hash=payload.weights_hash,
        applicability=payload.applicability, actor=user.subject,
    )
    db.commit()
    return _out(m)


@router.post("/{candidate_id}/evaluate")
def evaluate(
    candidate_id: uuid.UUID,
    payload: PromotionEvidenceIn,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """Показать, готов ли кандидат к продвижению, и почему нет (сухой прогон гейта)."""
    candidate = db.get(ModelVersion, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    gate = evaluate_promotion(
        candidate_status=candidate.status,
        frozen_test_cases=payload.frozen_test_cases,
        frozen_test_superior=payload.frozen_test_superior,
        shadow_rejection_rate=payload.shadow_rejection_rate,
        no_regression_on_new_devices=payload.no_regression_on_new_devices,
        criteria=PromotionCriteria(),
    )
    return {"ok": gate.ok, "reasons": gate.reasons}


@router.post("/{candidate_id}/promote", response_model=ModelOut)
def promote(
    candidate_id: uuid.UUID,
    payload: PromoteIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> ModelOut:
    candidate = db.get(ModelVersion, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    gate = evaluate_promotion(
        candidate_status=candidate.status,
        frozen_test_cases=payload.frozen_test_cases,
        frozen_test_superior=payload.frozen_test_superior,
        shadow_rejection_rate=payload.shadow_rejection_rate,
        no_regression_on_new_devices=payload.no_regression_on_new_devices,
    )
    try:
        m = model_registry.promote(
            db, candidate_id=candidate_id, gate=gate,
            actor=user.subject, justification=payload.justification,
        )
        db.commit()
    except PromotionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(m)


@router.post("/{version_id}/rollback", response_model=ModelOut)
def rollback(
    version_id: uuid.UUID,
    payload: RollbackIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> ModelOut:
    """Мгновенный откат к указанной версии (FR-10, п. 6)."""
    try:
        m = model_registry.rollback(
            db, to_version_id=version_id, actor=user.subject, reason=payload.reason,
        )
        db.commit()
    except PromotionError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _out(m)
