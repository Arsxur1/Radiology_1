"""Находки и правки врача (ТЗ, FR-9, SR-2, SR-6).

Каждое действие — отдельный явный вызов по одной находке. Нет «принять всё»
и авто-принятия (SR-2). Каждое решение порождает correction (обучающий сигнал).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.audit import AuditAction
from app.models.imaging import Series
from app.models.ml import Finding, FindingSource, InferenceResult
from app.services import audit, corrections
from app.services.corrections import CorrectionError
from app.services.mode_state import model_results_visible

router = APIRouter(prefix="/findings", tags=["findings"])


class FindingOut(BaseModel):
    id: uuid.UUID
    series_id: uuid.UUID
    coding_system: str
    code: str | None
    label: str | None
    measurements: dict
    source: str
    confirmation_status: str
    # Есть ли тепловая карта «куда смотрела модель» (GET /findings/{id}/heatmap).
    has_heatmap: bool = False
    # Состояние 3D-модели (FR-5): queued / ready / failed и статистика; без ссылок на хранилище.
    mesh: dict | None = None
    # Код причины отклонения (SR-6) — только для отклонённых находок.
    reject_reason: str | None = None


class ConfirmIn(BaseModel):
    time_spent_seconds: float | None = None


class ModifyIn(BaseModel):
    measurements: dict | None = None
    code: str | None = None
    label: str | None = None
    coordinates: dict | None = None
    time_spent_seconds: float | None = None


class RejectIn(BaseModel):
    reason: str | None = None              # код из GET /findings/reject-reasons
    time_spent_seconds: float | None = None


class RejectReasonIn(BaseModel):
    reason: str


class CreateFindingIn(BaseModel):
    series_id: uuid.UUID
    measurements: dict = {}
    code: str | None = None
    label: str | None = None
    coordinates: dict | None = None
    coding_system: str = "RadLex"
    time_spent_seconds: float | None = None


def _out(f: Finding, db: Session | None = None) -> FindingOut:
    rejected = f.confirmation_status.value == "rejected"
    return FindingOut(
        id=f.id,
        series_id=f.series_id,
        coding_system=f.coding_system,
        code=f.code,
        label=f.label,
        measurements=f.measurements,
        source=f.source.value,
        confirmation_status=f.confirmation_status.value,
        has_heatmap=bool((f.coordinates or {}).get("heatmap_ref")),
        mesh=_mesh_public((f.coordinates or {}).get("mesh")),
        reject_reason=corrections.reject_reason_of(db, f.id) if rejected and db is not None else None,
    )


def _mesh_public(state: dict | None) -> dict | None:
    if not state:
        return None
    return {k: v for k, v in state.items() if k not in ("stl", "glb")}


@router.get("/series/{series_id}", response_model=list[FindingOut])
def list_series_findings(series_id: uuid.UUID, db: Session = Depends(get_db)) -> list[FindingOut]:
    """Находки серии. В режиме SHADOW результаты модели не показываются (раздел 2);
    результаты теневого прогона модели-кандидата не показываются никогда;
    находки самого врача видны всегда."""
    rows = db.execute(
        select(Finding)
        .outerjoin(InferenceResult, Finding.inference_result_id == InferenceResult.id)
        .where(Finding.series_id == series_id)
        .where((InferenceResult.id.is_(None)) | (InferenceResult.shadow_run.is_(False)))
    ).scalars().all()
    series = db.get(Series, series_id)
    modality = series.modality if series else None
    if not model_results_visible(db, modality):
        rows = [f for f in rows if f.source != FindingSource.MODEL]
    return [_out(f, db) for f in rows]


def heatmap_ref_for(db: Session, finding_id: uuid.UUID) -> str:
    """Ссылка на тепловую карту, если врачу её можно показать; иначе LookupError."""
    f = db.get(Finding, finding_id)
    if f is None or f.source != FindingSource.MODEL:
        raise LookupError("Находка модели не найдена")
    if f.inference_result is not None and f.inference_result.shadow_run:
        raise LookupError("Находка модели не найдена")  # теневой прогон не раскрываем
    series = db.get(Series, f.series_id)
    if not model_results_visible(db, series.modality if series else None):
        raise LookupError("Результаты модели в текущем режиме не показываются")
    ref = (f.coordinates or {}).get("heatmap_ref")
    if not ref:
        raise LookupError("Для находки нет тепловой карты")
    return ref


@router.get("/{finding_id}/heatmap")
def heatmap(
    finding_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.RADIOLOGIST, Role.ADMIN, Role.RESEARCHER)),
) -> Response:
    """PNG «куда смотрела модель» — подсказка, не разметка патологии (SR-1)."""
    from app.services import storage

    try:
        ref = heatmap_ref_for(db, finding_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(content=storage.get_object_ref(ref), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


@router.post("/{finding_id}/confirm", response_model=FindingOut)
def confirm(
    finding_id: uuid.UUID,
    payload: ConfirmIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> FindingOut:
    try:
        corrections.confirm_finding(
            db, finding_id=finding_id, physician=user.subject,
            time_spent_seconds=payload.time_spent_seconds,
        )
        db.commit()
    except CorrectionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db.get(Finding, finding_id), db)


@router.post("/{finding_id}/modify", response_model=FindingOut)
def modify(
    finding_id: uuid.UUID,
    payload: ModifyIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> FindingOut:
    try:
        corrections.modify_finding(
            db, finding_id=finding_id, physician=user.subject,
            new_measurements=payload.measurements, new_code=payload.code,
            new_label=payload.label, new_coordinates=payload.coordinates,
            time_spent_seconds=payload.time_spent_seconds,
        )
        db.commit()
    except CorrectionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db.get(Finding, finding_id), db)


@router.post("/{finding_id}/reject", response_model=FindingOut)
def reject(
    finding_id: uuid.UUID,
    payload: RejectIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> FindingOut:
    if payload.reason and payload.reason not in corrections.REJECT_REASONS:
        raise HTTPException(status_code=422, detail="Неизвестная причина отклонения")
    try:
        corrections.reject_finding(
            db, finding_id=finding_id, physician=user.subject,
            reason=payload.reason, time_spent_seconds=payload.time_spent_seconds,
        )
        db.commit()
    except CorrectionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db.get(Finding, finding_id), db)


class RejectReasonOut(BaseModel):
    code: str
    label: str


@router.get("/reject-reasons", response_model=list[RejectReasonOut])
def reject_reasons() -> list[RejectReasonOut]:
    """Закрытый список причин отклонения находки (SR-6)."""
    return [RejectReasonOut(code=k, label=v) for k, v in corrections.REJECT_REASONS.items()]


@router.post("/{finding_id}/reject-reason", response_model=FindingOut)
def reject_reason(
    finding_id: uuid.UUID,
    payload: RejectReasonIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> FindingOut:
    """Уточнить причину после отклонения в одно действие (необязательно)."""
    if payload.reason not in corrections.REJECT_REASONS:
        raise HTTPException(status_code=422, detail="Неизвестная причина отклонения")
    try:
        corrections.set_reject_reason(db, finding_id=finding_id, physician=user.subject, reason=payload.reason)
        db.commit()
    except CorrectionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _out(db.get(Finding, finding_id), db)


@router.post("", response_model=FindingOut)
def create(
    payload: CreateFindingIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST)),
) -> FindingOut:
    """Врач добавляет находку, пропущенную моделью (обучающий сигнал)."""
    if db.get(Series, payload.series_id) is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    try:
        finding = corrections.create_physician_finding(
            db, series_id=payload.series_id, physician=user.subject,
            measurements=payload.measurements, code=payload.code, label=payload.label,
            coordinates=payload.coordinates, coding_system=payload.coding_system,
            time_spent_seconds=payload.time_spent_seconds,
        )
    except CorrectionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    db.commit()
    return _out(finding)


# --- 3D-модели (FR-5) ---

MESH_FORMATS = {"stl": ("model/stl", "stl"), "glb": ("model/gltf-binary", "glb")}


def enqueue_mesh(finding_id: uuid.UUID) -> None:
    from app.workers.celery_app import celery_app

    celery_app.send_task("mesh.build", args=[str(finding_id)])


def _visible_mesh_source(db: Session, finding_id: uuid.UUID):
    from app.services.mesh_builder import mesh_source

    src = mesh_source(db, finding_id)
    if not model_results_visible(db, src.series.modality if src.series else None):
        raise LookupError("Результаты модели в текущем режиме не показываются")
    return src


@router.post("/{finding_id}/mesh", response_model=FindingOut, status_code=202)
def request_mesh(
    finding_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.RADIOLOGIST, Role.CLINICIAN, Role.RESEARCHER)),
) -> FindingOut:
    """Поставить построение 3D-модели в очередь. Отказ гейта FR-5 — 422 с причиной."""
    from app.services.mesh_builder import MeshRefused, set_mesh_state

    try:
        src = _visible_mesh_source(db, finding_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except MeshRefused as e:
        raise HTTPException(status_code=422, detail=e.reason) from e
    if ((src.finding.coordinates or {}).get("mesh") or {}).get("status") != "ready":
        set_mesh_state(src.finding, {"status": "queued"})
        db.commit()
        enqueue_mesh(finding_id)
    return _out(src.finding)


@router.get("/{finding_id}/mesh.{fmt}")
def download_mesh(
    finding_id: uuid.UUID,
    fmt: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(Role.RADIOLOGIST, Role.CLINICIAN, Role.RESEARCHER)),
) -> Response:
    """STL (печать) или GLB (просмотр в браузере). Выгрузка записывается в журнал аудита."""
    from app.services import storage
    from app.services.mesh_builder import MeshRefused

    if fmt not in MESH_FORMATS:
        raise HTTPException(status_code=404, detail="Формат: stl или glb")
    try:
        src = _visible_mesh_source(db, finding_id)
    except (LookupError, MeshRefused) as e:
        raise HTTPException(status_code=404, detail=getattr(e, "reason", str(e))) from e
    state = (src.finding.coordinates or {}).get("mesh") or {}
    if state.get("status") != "ready" or not state.get(fmt):
        raise HTTPException(status_code=404, detail="3D-модель ещё не построена")
    audit.record_access(db, user, AuditAction.EXPORT, entity_type="mesh", entity_id=finding_id,
                        details={"format": fmt, "structure_key": src.structure_key})
    media, ext = MESH_FORMATS[fmt]
    return Response(content=storage.get_object_ref(state[fmt]), media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{src.structure_key}.{ext}"',
        "Cache-Control": "private, no-store",
    })
