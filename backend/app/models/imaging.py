"""Исследование и серия (ТЗ, раздел 5).

Пиксельные данные в БД не хранятся — только ссылки (Orthanc ID, S3-ключи),
метаданные и признаки пригодности для 3D/модели.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Study(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "study"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("patient.id"), nullable=False, index=True
    )

    # Обезличенный StudyInstanceUID (после де-ид). Уникален.
    study_instance_uid: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    modality: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # CT/MR/CR/DX…
    study_date: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Аппарат: производитель, модель, версия ПО, протокол.
    manufacturer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manufacturer_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    protocol: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Ссылка на исследование в чистом Orthanc.
    orthanc_study_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    patient = relationship("Patient", back_populates="studies")
    series: Mapped[list[Series]] = relationship(
        back_populates="study", cascade="all, delete-orphan"
    )


class Series(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "series"

    study_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("study.id"), nullable=False, index=True
    )
    series_instance_uid: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    series_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modality: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    instance_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Ключевые поля для определения пригодности к 3D/модели (ТЗ, раздел 5).
    slice_thickness_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    voxel_spacing: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # [x,y,z] мм
    transfer_syntax: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lossy_compressed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contrast_agent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Ссылки на объекты (пиксели — не в БД).
    orthanc_series_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    object_prefix: Mapped[str | None] = mapped_column(String(256), nullable=True)  # префикс в MinIO

    study: Mapped[Study] = relationship(back_populates="series")

    def is_3d_capable(self) -> bool:
        """Грубая пригодность к 3D: есть толщина среза и она достаточно мала.

        Точный порог для конкретной модели задаётся её границами применимости
        (SR-7) и проверяется отдельно на этапе 2.
        """
        if self.slice_thickness_mm is None:
            return False
        return self.slice_thickness_mm <= 3.0 and not self.lossy_compressed
