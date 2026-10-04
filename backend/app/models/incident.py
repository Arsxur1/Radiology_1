"""Журнал инцидентов (ТЗ, раздел 9 п. 7: порядок разбора инцидентов; пострегистрационный
надзор). Сообщает врач или клиницист; разбирает и закрывает ответственное лицо (админ)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.types import GUID


class IncidentKind(str, Enum):
    AI_MISLEADING = "ai_misleading"        # находка ИИ могла повлиять на решение
    AI_MISSED = "ai_missed"                # ИИ пропустил значимую находку
    WRONG_PATIENT = "wrong_patient"        # неверная привязка пациента/исследования
    SYSTEM_FAILURE = "system_failure"      # недоступность, потеря или искажение данных
    PRIVACY = "privacy"                    # раскрытие персональных данных
    OTHER = "other"


class IncidentSeverity(str, Enum):
    NEAR_MISS = "near_miss"   # замечено до последствий
    MODERATE = "moderate"     # повлияло на работу, без вреда пациенту
    SERIOUS = "serious"       # мог быть / причинён вред пациенту — срочный разбор


class IncidentStatus(str, Enum):
    NEW = "new"
    INVESTIGATING = "investigating"
    CLOSED = "closed"


class Incident(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "incident"

    reported_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reporter_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[IncidentKind] = mapped_column(SAEnum(IncidentKind, name="incident_kind"), nullable=False)
    severity: Mapped[IncidentSeverity] = mapped_column(
        SAEnum(IncidentSeverity, name="incident_severity"), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        SAEnum(IncidentStatus, name="incident_status"), nullable=False, default=IncidentStatus.NEW)
    # Привязка к обезличенным сущностям — пациент определяется по исследованию, ФИО не пишется.
    study_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("study.id"), nullable=True)
    finding_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("finding.id"), nullable=True)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("model_version.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
