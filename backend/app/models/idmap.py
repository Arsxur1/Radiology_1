"""Таблица сопоставления «реальный идентификатор ↔ обезличенный UUID» (SR-9).

Живёт в ОТДЕЛЬНОЙ БД идентифицирующего контура (postgres-idmap). Собственная
декларативная база, чтобы эти таблицы физически не смешивались с доверенным
контуром и не попадали в его миграции.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import GUID


class IdMapBase(DeclarativeBase):
    """База идентифицирующего контура (изолирована от доверенного)."""


class PatientPseudonymMap(IdMapBase):
    __tablename__ = "patient_pseudonym_map"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    # Обезличенный UUID пациента в доверенном контуре.
    pseudonym_patient_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False, index=True
    )
    # Реальные идентификаторы (PHI) — только здесь.
    source_issuer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    real_mrn: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    real_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Соответствие обезличенных и реальных DICOM UID.
    real_study_instance_uid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pseudonym_study_instance_uid: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
