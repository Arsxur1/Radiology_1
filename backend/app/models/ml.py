"""Версии моделей, результаты инференса, правки, находки, черновики (ТЗ, раздел 5).

Задел под этапы 2–3. На этапе 1 таблицы создаются, но не наполняются моделями.
Ключевой инвариант: разделение «модель посчитала» / «врач подтвердил».
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class ModelStatus(str, Enum):
    SHADOW = "shadow"
    ACTIVE = "active"
    RETIRED = "retired"


class FindingSource(str, Enum):
    MODEL = "model"
    PHYSICIAN = "physician"


class ConfirmationStatus(str, Enum):
    PENDING = "pending"        # не подтверждено врачом (значение по умолчанию)
    CONFIRMED = "confirmed"    # подтверждено активным действием врача (SR-2)
    REJECTED = "rejected"      # отклонено врачом (SR-6)


class CorrectionType(str, Enum):
    ACCEPTED = "accepted"
    MODIFIED = "modified"
    REJECTED = "rejected"


class ModelVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "model_version"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    semver: Mapped[str] = mapped_column(String(32), nullable=False)
    weights_hash: Mapped[str] = mapped_column(String(128), nullable=False)  # хеш весов (SR-5)
    installed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Границы применимости (SR-7): толщина среза, возраст, модальность, контраст, аппарат.
    applicability: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[ModelStatus] = mapped_column(
        SAEnum(ModelStatus, name="model_status"), default=ModelStatus.SHADOW, nullable=False
    )


class InferenceResult(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "inference_result"

    series_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("series.id"), nullable=False, index=True
    )
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("model_version.id"), nullable=False
    )
    # Полная трассировка (SR-5): артефакт, время, метрики, параметры препроцессинга.
    artifact_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)  # S3-ключ
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preprocessing_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    model_version: Mapped[ModelVersion] = relationship()
    findings: Mapped[list[Finding]] = relationship(back_populates="inference_result")


class Finding(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "finding"

    series_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("series.id"), nullable=False, index=True
    )
    inference_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("inference_result.id"), nullable=True
    )
    # Код локализации: SNOMED CT либо RadLex (по умолчанию RadLex, см. VOPROSY-K-TZ.md).
    coding_system: Mapped[str] = mapped_column(String(32), default="RadLex", nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Измерения: объёмы, линейные размеры, плотности, соотношения.
    measurements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Привязка к координатам в серии.
    coordinates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    source: Mapped[FindingSource] = mapped_column(
        SAEnum(FindingSource, name="finding_source"), nullable=False
    )
    confirmation_status: Mapped[ConfirmationStatus] = mapped_column(
        SAEnum(ConfirmationStatus, name="confirmation_status"),
        default=ConfirmationStatus.PENDING,
        nullable=False,
    )
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)  # subject врача

    inference_result: Mapped[InferenceResult | None] = relationship(back_populates="findings")


class Correction(UUIDMixin, TimestampMixin, Base):
    """Правка врача — обучающий сигнал (FR-9, SR-6). Порождается любой правкой."""

    __tablename__ = "correction"

    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("finding.id"), nullable=True, index=True
    )
    series_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("series.id"), nullable=False, index=True
    )
    correction_type: Mapped[CorrectionType] = mapped_column(
        SAEnum(CorrectionType, name="correction_type"), nullable=False
    )
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # было
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)   # стало
    author: Mapped[str] = mapped_column(String(128), nullable=False)   # subject врача
    time_spent_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class Report(UUIDMixin, TimestampMixin, Base):
    """Черновик заключения. Собирается ТОЛЬКО из подтверждённых находок (FR-8).

    Обратный разбор текста в находки запрещён (нет соответствующих операций).
    """

    __tablename__ = "report"

    study_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("study.id"), nullable=False, index=True
    )
    # Текст черновика; каждое предложение трассируется до finding (sentence_map).
    draft_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentence_map: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    language: Mapped[str] = mapped_column(String(8), default="ru", nullable=False)
    finalized_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
