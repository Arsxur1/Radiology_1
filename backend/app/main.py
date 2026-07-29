"""Точка входа FastAPI (этап 1, RESEARCH)."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_audit, routes_health, routes_modes, routes_studies
from app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(
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

app.include_router(routes_health.router)
app.include_router(routes_studies.router)
app.include_router(routes_modes.router)
app.include_router(routes_audit.router)


@app.get("/")
def root() -> dict:
    return {
        "name": "medviz",
        "stage": 1,
        "mode": settings.default_operating_mode,
        "disclaimer": "Не для клинического применения на этапе RESEARCH",
    }
