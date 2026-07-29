"""Совмещение модальностей — регистрация (ТЗ, FR-4). Задел под этап 6.

Инвариант: совмещение с неподтверждённым качеством НЕ используется для измерений.
Поэтому у регистрации есть и количественная оценка качества, и статус проверки
врачом; измерения на её основе допускаются только при подтверждённом качестве.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.types import GUID, JSONB


class RegistrationStage(str, Enum):
    """Последовательность совмещения (ТЗ, FR-4): жёсткая → аффинная → деформируемая."""

    RIGID = "rigid"
    AFFINE = "affine"
    DEFORMABLE = "deformable"


class RegistrationReview(str, Enum):
    PENDING = "pending"        # качество не подтверждено врачом (по умолчанию)
    APPROVED = "approved"      # врач подтвердил визуально
    REJECTED = "rejected"      # врач отклонил результат совмещения


class Registration(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "registration"

    # Совмещаются две серии одного пациента (напр. КТ и МРТ).
    fixed_series_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("series.id"), nullable=False, index=True
    )
    moving_series_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("series.id"), nullable=False, index=True
    )
    # Достигнутая стадия (rigid/affine/deformable).
    stage: Mapped[RegistrationStage] = mapped_column(
        SAEnum(RegistrationStage, name="registration_stage"), nullable=False
    )
    # Метрика для разных модальностей — mutual information (FR-4).
    metric_name: Mapped[str] = mapped_column(String(64), default="mutual_information", nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Количественная оценка качества совмещения (обязательна, FR-4).
    quality: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Ссылка на артефакт трансформации (в объектном хранилище).
    transform_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    review_status: Mapped[RegistrationReview] = mapped_column(
        SAEnum(RegistrationReview, name="registration_review"),
        default=RegistrationReview.PENDING,
        nullable=False,
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    def usable_for_measurements(self) -> bool:
        """Совмещение годно для измерений только при подтверждённом врачом качестве (FR-4)."""
        return self.review_status == RegistrationReview.APPROVED
