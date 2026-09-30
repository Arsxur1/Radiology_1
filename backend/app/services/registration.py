"""Совмещение модальностей (ТЗ, FR-4).

Последовательность обязательна: жёсткая → аффинная → деформируемая. Метрика для
разных модальностей — mutual information. Обязателен количественный вывод качества
и визуальная проверка врачом. Совмещение с неподтверждённым качеством НЕ идёт в
измерения.

Движок — SimpleITK (`services/registration_engines.py`), считается в воркере.
Детерминированная заглушка — только для демо: её результат подтвердить нельзя.
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


class RegistrationBlocked(RegistrationError):
    """Подтвердить совмещение нельзя (не посчитано, заглушка, «складки» деформации)."""


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


def _check_pair(fixed_series: Series, moving_series: Series) -> None:
    if fixed_series.study.patient_id != moving_series.study.patient_id:
        raise RegistrationError("Серии принадлежат разным пациентам")
    if fixed_series.id == moving_series.id:
        raise RegistrationError("Нельзя совмещать серию с самой собой")


def queue_registration(
    db: Session,
    *,
    fixed_series: Series,
    moving_series: Series,
    up_to_stage: RegistrationStage = RegistrationStage.DEFORMABLE,
    actor: str = "system",
) -> Registration:
    """Создать совмещение в статусе «в очереди»; считает воркер (`workers/registration_tasks.py`)."""
    _check_pair(fixed_series, moving_series)
    reg = Registration(
        fixed_series_id=fixed_series.id, moving_series_id=moving_series.id, stage=up_to_stage,
        metric_name="mutual_information", metric_value=None, quality={"status": "queued"},
        review_status=RegistrationReview.PENDING,
    )
    db.add(reg)
    db.flush()
    audit.record(db, actor=actor, action=AuditAction.CORRECTION, entity_type="registration", entity_id=reg.id,
                 details={"event": "registration_queued", "requested_stage": up_to_stage.value})
    return reg


def apply_output(db: Session, reg: Registration, output: RegistrationOutput, *, requested: RegistrationStage,
                 actor: str = "system") -> Registration:
    """Записать результат движка. Достигнутая стадия может быть ниже запрошенной, если
    следующая стадия ухудшила совмещение (движок её отбрасывает и сообщает об этом)."""
    reg.stage = output.stage
    reg.metric_value = output.metric_value
    reg.quality = {**output.quality, "status": "done", "requested_stage": requested.value}
    reg.transform_ref = output.transform_ref
    db.flush()
    audit.record(db, actor=actor, action=AuditAction.CORRECTION, entity_type="registration", entity_id=reg.id,
                 details={"event": "registration_run", "stage": output.stage.value,
                          "metric_value": output.metric_value})
    return reg


def run_registration(
    db: Session,
    *,
    fixed_series: Series,
    moving_series: Series,
    engine: RegistrationEngine,
    up_to_stage: RegistrationStage = RegistrationStage.DEFORMABLE,
    actor: str = "system",
) -> Registration:
    """Выполнить совмещение синхронно до указанной стадии (review=pending).

    Требует, чтобы обе серии принадлежали одному пациенту. Результат создаётся
    неподтверждённым: для измерений не годен, пока врач не подтвердит качество.
    """
    reg = queue_registration(db, fixed_series=fixed_series, moving_series=moving_series,
                             up_to_stage=up_to_stage, actor=actor)
    output = engine.register(
        fixed_series.object_prefix or fixed_series.series_instance_uid,
        moving_series.object_prefix or moving_series.series_instance_uid,
        up_to_stage,
    )
    return apply_output(db, reg, output, requested=up_to_stage, actor=actor)


def review_blockers(reg: Registration) -> list[str]:
    """Почему врач не может подтвердить совмещение (пусто — может)."""
    q = reg.quality or {}
    status = q.get("status", "done")
    if status != "done":
        return [{"queued": "Совмещение ещё в очереди", "running": "Совмещение ещё считается",
                 "failed": f"Совмещение не удалось: {q.get('error', '')}"}.get(status, status)]
    out = [w["text"] for w in q.get("warnings", []) if w.get("blocking")]
    if q.get("engine") == "stub":
        out.append("Демо-заглушка: результат не настоящий и не может быть подтверждён")
    return out


def review_registration(
    db: Session, *, registration_id: uuid.UUID, approved: bool, physician: str
) -> Registration:
    """Визуальная проверка врачом (FR-4): подтвердить или отклонить совмещение."""
    reg = db.get(Registration, registration_id)
    if reg is None:
        raise RegistrationError("Совмещение не найдено")
    blockers = review_blockers(reg) if approved else []
    if blockers:
        raise RegistrationBlocked("; ".join(blockers))

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
