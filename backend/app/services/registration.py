"""Совмещение модальностей (ТЗ, FR-4). Задел под этап 6, режим ASSIST.

Последовательность обязательна: жёсткая → аффинная → деформируемая. Метрика для
разных модальностей — mutual information. Обязателен количественный вывод качества
и визуальная проверка врачом. Совмещение с неподтверждённым качеством НЕ идёт в
измерения.

Тяжёлая регистрация (SimpleITK/Elastix или ANTs) подключается на стенде; здесь —
контур, оценка качества и гейты. Адаптер абстрагирован, детерминированная заглушка
позволяет собрать контур и тесты без нативных библиотек.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.audit import AuditAction
from app.models.imaging import Series
from app.models.registration import Registration, RegistrationReview, RegistrationStage
from app.services import audit

#: Обязательный порядок этапов совмещения (FR-4).
STAGE_ORDER = [RegistrationStage.RIGID, RegistrationStage.AFFINE, RegistrationStage.DEFORMABLE]


class RegistrationError(Exception):
    """Нарушение процедуры совмещения."""


@dataclass
class RegistrationOutput:
    stage: RegistrationStage
    metric_value: float               # значение mutual information (больше — лучше)
    quality: dict = field(default_factory=dict)
    transform_ref: str | None = None


class RegistrationEngine(ABC):
    """Контракт движка совмещения."""

    @abstractmethod
    def register(
        self, fixed_prefix: str, moving_prefix: str, up_to_stage: RegistrationStage
    ) -> RegistrationOutput:
        raise NotImplementedError


class StubRegistrationEngine(RegistrationEngine):
    """Детерминированная заглушка без нативных библиотек (для контура и тестов)."""

    def register(
        self, fixed_prefix: str, moving_prefix: str, up_to_stage: RegistrationStage
    ) -> RegistrationOutput:
        import hashlib

        seed = int(hashlib.sha256((fixed_prefix + "|" + moving_prefix).encode()).hexdigest()[:8], 16)
        # Более поздняя стадия — выше mutual information (детерминированно).
        base = 0.4 + (seed % 100) / 500.0
        bonus = {RegistrationStage.RIGID: 0.0, RegistrationStage.AFFINE: 0.1,
                 RegistrationStage.DEFORMABLE: 0.2}[up_to_stage]
        mi = round(base + bonus, 4)
        return RegistrationOutput(
            stage=up_to_stage,
            metric_value=mi,
            quality={"mutual_information": mi, "engine": "stub"},
            transform_ref=f"{moving_prefix}/transform_{up_to_stage.value}.tfm",
        )


def run_registration(
    db: Session,
    *,
    fixed_series: Series,
    moving_series: Series,
    engine: RegistrationEngine,
    up_to_stage: RegistrationStage = RegistrationStage.DEFORMABLE,
    actor: str = "system",
) -> Registration:
    """Выполнить совмещение до указанной стадии и сохранить результат (review=pending).

    Требует, чтобы обе серии принадлежали одному пациенту. Результат создаётся
    неподтверждённым: для измерений не годен, пока врач не подтвердит качество.
    """
    if fixed_series.study.patient_id != moving_series.study.patient_id:
        raise RegistrationError("Серии принадлежат разным пациентам")
    if fixed_series.id == moving_series.id:
        raise RegistrationError("Нельзя совмещать серию с самой собой")

    output = engine.register(
        fixed_series.object_prefix or fixed_series.series_instance_uid,
        moving_series.object_prefix or moving_series.series_instance_uid,
        up_to_stage,
    )

    reg = Registration(
        fixed_series_id=fixed_series.id,
        moving_series_id=moving_series.id,
        stage=output.stage,
        metric_name="mutual_information",
        metric_value=output.metric_value,
        quality=output.quality,
        transform_ref=output.transform_ref,
        review_status=RegistrationReview.PENDING,
    )
    db.add(reg)
    db.flush()

    audit.record(
        db,
        actor=actor,
        action=AuditAction.CORRECTION,
        entity_type="registration",
        entity_id=reg.id,
        details={
            "event": "registration_run",
            "stage": output.stage.value,
            "metric_value": output.metric_value,
        },
    )
    return reg


def review_registration(
    db: Session, *, registration_id: uuid.UUID, approved: bool, physician: str
) -> Registration:
    """Визуальная проверка врачом (FR-4): подтвердить или отклонить совмещение."""
    reg = db.get(Registration, registration_id)
    if reg is None:
        raise RegistrationError("Совмещение не найдено")

    reg.review_status = RegistrationReview.APPROVED if approved else RegistrationReview.REJECTED
    reg.reviewed_by = physician
    db.flush()

    audit.record(
        db,
        actor=physician,
        actor_role="radiologist",
        action=AuditAction.CORRECTION,
        entity_type="registration",
        entity_id=reg.id,
        details={"event": "registration_review", "approved": approved},
    )
    return reg


def ensure_usable_for_measurements(reg: Registration) -> None:
    """Гейт FR-4: измерения на основе совмещения — только при подтверждённом качестве."""
    if not reg.usable_for_measurements():
        raise RegistrationError(
            "Совмещение с неподтверждённым качеством не используется для измерений "
            f"(статус проверки: {reg.review_status.value})"
        )
