"""Точка входа FastAPI (этап 1, RESEARCH)."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_audit,
    routes_auth,
    routes_classification,
    routes_findings,
    routes_health,
    routes_incidents,
    routes_learning,
    routes_models,
    routes_modes,
    routes_pacs,
    routes_patients,
    routes_pilot,
    routes_registration,
    routes_reports,
    routes_segmentation,
    routes_studies,
    routes_system,
    routes_temporal,
    routes_vocabulary,
)
from app.api.deps import get_current_user
from app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Бакеты хранилища — в фоне: запуск API (и просмотр) не ждёт хранилище (SR-4).
    from app.services.storage import ensure_buckets_safely

    threading.Thread(target=ensure_buckets_safely, name="ensure-buckets", daemon=True).start()
    yield


app = FastAPI(
    lifespan=_lifespan,
    title="Платформа анализа медицинских изображений",
    version="0.1.0",
    description=(
        "Этап 1 (RESEARCH). Система не ставит диагноз и не заменяет врача. "
        "Ни один вывод модели не попадает в медицинскую документацию без "
        "явного подтверждения врача."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Без аутентификации — только проверки живости для мониторинга (/health, /ready).
# Всё остальное требует пользователя (FR-12); роли уточняются на уровне маршрутов.
_AUTH = [Depends(get_current_user)]

app.include_router(routes_health.router)
# /auth/config публичный, /auth/check проверяет пользователя сам.
app.include_router(routes_auth.router)
app.include_router(routes_studies.router, dependencies=_AUTH)
app.include_router(routes_modes.router, dependencies=_AUTH)
app.include_router(routes_audit.router, dependencies=_AUTH)
app.include_router(routes_findings.router, dependencies=_AUTH)
app.include_router(routes_models.router, dependencies=_AUTH)
app.include_router(routes_learning.router, dependencies=_AUTH)
app.include_router(routes_segmentation.router, dependencies=_AUTH)
app.include_router(routes_classification.router, dependencies=_AUTH)
app.include_router(routes_temporal.router, dependencies=_AUTH)
app.include_router(routes_reports.router, dependencies=_AUTH)
app.include_router(routes_pacs.router, dependencies=_AUTH)
app.include_router(routes_patients.router, dependencies=_AUTH)
app.include_router(routes_registration.router, dependencies=_AUTH)
app.include_router(routes_vocabulary.router, dependencies=_AUTH)
app.include_router(routes_pilot.router, dependencies=_AUTH)
app.include_router(routes_system.router, dependencies=_AUTH)
app.include_router(routes_incidents.router, dependencies=_AUTH)


@app.get("/")
def root() -> dict:
    return {
        "name": "medviz",
        "stage": 1,
        "mode": settings.default_operating_mode,
        "disclaimer": "Не для клинического применения на этапе RESEARCH",
    }
