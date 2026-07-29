"""Health/readiness. Отказ модуля ИИ не влияет на доступность просмотра (SR-4)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "stage": 1, "mode_note": "RESEARCH — не для клинического применения"}


@router.get("/ready")
def ready() -> dict:
    # Просмотр и архив не зависят от модуля ИИ (на этапе 1 моделей нет).
    return {"viewer": "ok", "ingest": "ok", "ai": "disabled_stage_1"}
