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
from app.services.model_registry import PromotionError

router = APIRouter(prefix="/models", tags=["models"])


class ModelOut(BaseModel):
    id: uuid.UUID
    name: str
    semver: str
    weights_hash: str
    status: str
    applicability: dict
    task: str
    operating_points: dict
    adapter: dict = {}


class RegisterIn(BaseModel):
    name: str
    semver: str
    weights_hash: str
    applicability: dict = {}
    task: str = "segmentation"
    operating_points: dict = {}
    adapter: dict = {}


class PromoteIn(BaseModel):
    # Свидетельства гейт собирает сам (GET /models/{id}/evidence); от человека — только решение.
    justification: str


class RollbackIn(BaseModel):
    reason: str


class RollbackOut(BaseModel):
    # Версия, ставшая ACTIVE; None — ИИ этой линейки отключён (предыдущей версии нет).
    active: ModelOut | None


def _out(m: ModelVersion) -> ModelOut:
    return ModelOut(
        id=m.id, name=m.name, semver=m.semver, weights_hash=m.weights_hash,
        status=m.status.value, applicability=m.applicability,
        task=m.task, operating_points=m.operating_points or {}, adapter=m.adapter or {},
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
    try:
        m = model_registry.register_candidate(
            db, name=payload.name, semver=payload.semver, weights_hash=payload.weights_hash,
            applicability=payload.applicability, actor=user.subject,
            task=payload.task, operating_points=payload.operating_points, adapter=payload.adapter,
        )
    except PromotionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()
    return _out(m)


def _candidate_or_404(db: Session, candidate_id: uuid.UUID) -> ModelVersion:
    candidate = db.get(ModelVersion, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    return candidate


@router.post("/{candidate_id}/evaluate")
def evaluate(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """Готов ли кандидат к продвижению и почему нет. Свидетельства — из данных платформы:
    замороженный тест, теневой прогон, срезы по аппаратам и возрастным группам."""
    gate, evidence = model_registry.gate_for(db, _candidate_or_404(db, candidate_id))
    return {"ok": gate.ok, "reasons": gate.reasons, "evidence": evidence}


@router.post("/{candidate_id}/frozen-evaluation")
def frozen_evaluation(
    candidate_id: uuid.UUID,
    result: dict,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """Загрузить отчёт `cli evaluate` (замороженный тест). Принимается только для весов этой модели."""
    candidate = _candidate_or_404(db, candidate_id)
    try:
        frozen = model_registry.record_frozen_evaluation(db, candidate, result, actor=user.subject)
    except model_registry.EvidenceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()
    return frozen


@router.get("/{version_id}/shadow-report")
def shadow_report(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """Теневой прогон против подписанных заключений: данные для гейта (шаг 5)."""
    from app.services.shadow_eval import segmentation_shadow_report, shadow_report

    mv = db.get(ModelVersion, version_id)
    build = segmentation_shadow_report if mv is not None and mv.task == "segmentation" else shadow_report
    try:
        return build(db, version_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{version_id}/calibration")
def calibration(
    version_id: uuid.UUID,
    min_pos: int = 5,
    min_neg: int = 5,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """Предложение порогов по подписанным заключениям площадки (без изменения модели)."""
    from app.services.calibration import calibration_proposal

    try:
        return calibration_proposal(db, version_id, min_pos=min_pos, min_neg=min_neg)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{version_id}/calibrated-candidate", response_model=ModelOut)
def calibrated_candidate(
    version_id: uuid.UUID,
    min_pos: int = 5,
    min_neg: int = 5,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> ModelOut:
    """Новый кандидат (версия +1, SHADOW) с порогами, откалиброванными на площадке."""
    from app.services.calibration import CalibrationError, register_calibrated

    try:
        m = register_calibrated(db, version_id, actor=user.subject, min_pos=min_pos, min_neg=min_neg)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CalibrationError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    db.commit()
    return _out(m)


@router.post("/{candidate_id}/promote", response_model=ModelOut)
def promote(
    candidate_id: uuid.UUID,
    payload: PromoteIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> ModelOut:
    gate, evidence = model_registry.gate_for(db, _candidate_or_404(db, candidate_id))
    try:
        m = model_registry.promote(
            db, candidate_id=candidate_id, gate=gate,
            actor=user.subject, justification=payload.justification, evidence=evidence,
        )
        db.commit()
    except PromotionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(m)


@router.post("/{version_id}/rollback", response_model=RollbackOut)
def rollback(
    version_id: uuid.UUID,
    payload: RollbackIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> RollbackOut:
    """Мгновенный откат (FR-10, п. 6): к прежней версии или от текущей к предыдущей."""
    try:
        m = model_registry.rollback(
            db, to_version_id=version_id, actor=user.subject, reason=payload.reason,
        )
        db.commit()
    except model_registry.RollbackNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PromotionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return RollbackOut(active=_out(m) if m else None)
