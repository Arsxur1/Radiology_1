"""Health/readiness. Отказ модуля ИИ не влияет на доступность просмотра (SR-4)."""

from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "stage": 1, "mode_note": "RESEARCH — не для клинического применения"}


@router.get("/ready")
def ready(response: Response) -> dict:
    """Готовность по функциям: просмотр, приём, ИИ (ok / degraded / down). Без подробностей —
    эндпоинт публичный. 503, если не работает просмотр: без него платформа бесполезна (SR-4)."""
    from app.services.system_status import collect

    st = collect()
    if st["functions"]["viewer"] == "down":
        response.status_code = 503
    return {"status": st["status"], **st["functions"]}
