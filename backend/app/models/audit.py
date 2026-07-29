"""Аудит-лог и режимы работы (ТЗ, разделы 2 и 5).

Аудит-лог только на добавление (SR-8): UPDATE/DELETE запрещены на уровне прав
СУБД и триггером (см. миграцию 0002). Хеш-цепочка усиливает обнаружение подмены.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.modes import OperatingMode
from app.db.base import Base, UUIDMixin
from app.db.types import GUID, JSONB


class AuditAction(str, Enum):
    PATIENT_ACCESS = "patient_access"
    STUDY_INGEST = "study_ingest"
    ANONYMIZATION = "anonymization"
    MODE_CHANGE = "mode_change"
    FINDING_CONFIRM = "finding_confirm"
    FINDING_REJECT = "finding_reject"
    CORRECTION = "correction"
    REPORT_FINALIZE = "report_finalize"
    MODEL_PROMOTE = "model_promote"
    EXPORT = "export"


class AuditLog(UUIDMixin, Base):
    __tablename__ = "audit_log"

    # Нет updated_at и никаких операций изменения — только добавление.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False)  # subject из OIDC
    actor_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, name="audit_action"), nullable=False
    )
    # На какую сущность направлено действие.
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Хеш-цепочка: hash(prev_hash + payload). Позволяет обнаружить разрыв.
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class OperatingModeState(UUIDMixin, Base):
    """Текущий режим по установке и модальности (раздел 2).

    Смена — только администратором, с записью в audit_log. Историю смен
    отражает audit_log (action=mode_change), здесь — актуальное состояние.
    """

    __tablename__ = "operating_mode"

    # Область действия: конкретная модальность или '*' для всей установки.
    modality: Mapped[str] = mapped_column(String(16), nullable=False, default="*", unique=True)
    mode: Mapped[OperatingMode] = mapped_column(
        SAEnum(OperatingMode, name="operating_mode_enum"),
        default=OperatingMode.RESEARCH,
        nullable=False,
    )
    changed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
