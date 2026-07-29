"""Экспорт обучающих данных и контроль дрейфа (ТЗ, FR-9, FR-11).

Экспорт доступен инженеру-исследователю (только обезличенные данные, FR-12).
Метрики дрейфа — админу/аудитору.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_roles
from app.core.roles import Role
from app.db.session import get_db
from app.models.ml import CorrectionType
from app.services import dataset_export, drift
from app.services.dataset_export import ExportFilters

router = APIRouter(prefix="/learning", tags=["learning"])


class ExportRequest(BaseModel):
    modality: str | None = None
    manufacturer: str | None = None
    correction_types: list[CorrectionType] | None = None
    min_time_spent_seconds: float | None = None
    require_3d_capable: bool = False


@router.post("/export")
def export_training_set(
    req: ExportRequest,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.RESEARCHER, Role.ADMIN)),
) -> dict:
    """Экспорт обучающего набора с фильтрами (FR-9). Данные обезличены (SR-9)."""
    filters = ExportFilters(
        modality=req.modality,
        manufacturer=req.manufacturer,
        correction_types=req.correction_types or list(CorrectionType),
        min_time_spent_seconds=req.min_time_spent_seconds,
        require_3d_capable=req.require_3d_capable,
    )
    items = dataset_export.export(db, filters)
    return {"count": len(items), "items": [i.__dict__ for i in items]}


@router.get("/drift/rejection-rate")
def rejection_rate(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles(Role.ADMIN, Role.AUDITOR)),
) -> dict:
    """Доля отклонений врачом по производителю аппарата (FR-11).

    Рост доли на конкретном аппарате — сигнал деградации, невидимый по общей метрике.
    """
    rates = drift.rejection_rate_by_manufacturer(db)
    return {
        "slices": [
            {
                "dimension": r.slice_dimension,
                "value": r.slice_value,
                "total": r.total,
                "rejected": r.rejected,
                "rate": round(r.rate, 4),
            }
            for r in rates
        ]
    }
