"""Метрики дрейфа (ТЗ, раздел 5 и FR-11). Задел под этап 7."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin
from app.db.types import JSONB


class DataDriftMetric(UUIDMixin, Base):
    __tablename__ = "data_drift_metric"

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # Срез: аппарат, протокол, возрастная группа, клиника.
    slice_dimension: Mapped[str] = mapped_column(String(64), nullable=False)  # напр. "manufacturer"
    slice_value: Mapped[str] = mapped_column(String(128), nullable=False)
    clinic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Метрики распределения входов/выходов и доля отклонений врачом.
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
