"""Пациент и его идентификаторы (ТЗ, раздел 5).

Внутренний UUID — единственный первичный ключ. Номер карты клиники первичным
ключом быть не может. ФИО и внешние номера — в идентифицирующем контуре, здесь
только связь написаний → один пациент (транслитерация кириллица/латиница).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Patient(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "patient"

    # Никаких идентифицирующих полей: только внутренний UUID и связи.
    identifiers: Mapped[list[PatientIdentifier]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
        foreign_keys="PatientIdentifier.patient_id",
    )
    studies: Mapped[list["Study"]] = relationship(back_populates="patient")  # noqa: F821


class PatientIdentifier(UUIDMixin, TimestampMixin, Base):
    """Множество написаний ФИО/внешних номеров → один пациент.

    Хранит нормализованный ключ сопоставления (не сам PHI). Реальные значения
    (ФИО) остаются в идентифицирующем контуре. История merge/split — через
    поля active/merged_into.
    """

    __tablename__ = "patient_identifier"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("patient.id"), nullable=False, index=True
    )
    # Тип идентификатора: mrn (номер карты), name_translit, accession и т.п.
    id_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Нормализованное значение для сопоставления (напр. транслитерация ФИО).
    normalized_value: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Из какой системы пришёл идентификатор (issuer).
    issuer: Mapped[str | None] = mapped_column(String(128), nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Если запись объединена в другого пациента — куда именно (история merge).
    merged_into: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("patient.id"), nullable=True
    )

    patient: Mapped[Patient] = relationship(
        back_populates="identifiers", foreign_keys=[patient_id]
    )
