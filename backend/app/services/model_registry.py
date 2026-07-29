"""Контур развития моделей (ТЗ, FR-10, PCCP).

Обязательная последовательность, пропуск этапов не допускается:
  1. Фиксация — модель в ASSIST неизменна (SR-3).
  2. Накопление — данные копятся через правки (FR-9).
  3. Дообучение офлайн на отдельном контуре → модель-кандидат.
  4. Замороженный тест — сформирован до обучения, не открывается.
  5. Теневой прогон — кандидат в SHADOW параллельно действующей модели.
  6. Продвижение — осознанное документированное действие ответственного лица
     при превосходстве на замороженном тесте И в теневом прогоне.
     Обязателен мгновенный откат.

Ключевое: продвижение — не автоматическое. Здесь только гейт (проверка условий)
и запись решения в аудит. Само решение принимает ответственное лицо (роль admin).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditAction
from app.models.ml import ModelStatus, ModelVersion
from app.services import audit


class PromotionError(Exception):
    """Нарушение процедуры продвижения модели."""


@dataclass
class PromotionGate:
    """Результат проверки готовности кандидата к продвижению (шаг 6)."""

    ok: bool
    reasons: list[str] = field(default_factory=list)  # почему нельзя


@dataclass
class PromotionCriteria:
    """Пороги допуска. Конкретные числа согласуются до этапа 5 (раздел 9)."""

    min_frozen_test_cases: int = 100          # объём замороженного теста
    require_no_regression_new_devices: bool = True  # раздел 9, п. 3
    max_rejection_rate: float = 0.15          # доля отклонений врачом в теневом прогоне
    require_candidate_superior: bool = True   # превосходство на замороженном тесте


def evaluate_promotion(
    *,
    candidate_status: ModelStatus,
    frozen_test_cases: int,
    frozen_test_superior: bool,
    shadow_rejection_rate: float | None,
    no_regression_on_new_devices: bool,
    criteria: PromotionCriteria | None = None,
) -> PromotionGate:
    """Чистая проверка условий продвижения (шаг 6). Тестируемо без БД.

    Проверяет обязательную последовательность: кандидат обязан быть в SHADOW
    (прошёл теневой прогон), иметь замороженный тест достаточного объёма,
    превзойти действующую модель и не деградировать на новых аппаратах.
    """
    c = criteria or PromotionCriteria()
    reasons: list[str] = []

    # Шаг 5: кандидат должен пройти теневой прогон — значит быть в SHADOW.
    if candidate_status != ModelStatus.SHADOW:
        reasons.append(
            f"Кандидат в статусе {candidate_status.value}, требуется SHADOW "
            "(шаги 3–5 пропускать нельзя)"
        )

    # Шаг 4: замороженный тест достаточного объёма.
    if frozen_test_cases < c.min_frozen_test_cases:
        reasons.append(
            f"Замороженный тест: {frozen_test_cases} < {c.min_frozen_test_cases} исследований"
        )

    # Шаг 6: превосходство на замороженном тесте.
    if c.require_candidate_superior and not frozen_test_superior:
        reasons.append("Кандидат не превзошёл действующую модель на замороженном тесте")

    # Теневой прогон: доля отклонений врачом.
    if shadow_rejection_rate is None:
        reasons.append("Нет данных теневого прогона (доля отклонений не измерена)")
    elif shadow_rejection_rate > c.max_rejection_rate:
        reasons.append(
            f"Доля отклонений в теневом прогоне {shadow_rejection_rate:.2%} "
            f"> порога {c.max_rejection_rate:.2%}"
        )

    # Раздел 9, п. 3: отсутствие деградации на аппаратах вне обучения.
    if c.require_no_regression_new_devices and not no_regression_on_new_devices:
        reasons.append("Обнаружена деградация на аппаратах, не участвовавших в обучении")

    return PromotionGate(ok=not reasons, reasons=reasons)


def register_candidate(
    db: Session,
    *,
    name: str,
    semver: str,
    weights_hash: str,
    applicability: dict,
    actor: str,
) -> ModelVersion:
    """Зарегистрировать модель-кандидата. Всегда стартует в SHADOW (раздел 2)."""
    candidate = ModelVersion(
        name=name,
        semver=semver,
        weights_hash=weights_hash,
        applicability=applicability,
        status=ModelStatus.SHADOW,
        installed_at=datetime.now(timezone.utc),
    )
    db.add(candidate)
    db.flush()
    audit.record(
        db,
        actor=actor,
        actor_role="admin",
        action=AuditAction.MODEL_PROMOTE,
        entity_type="model_version",
        entity_id=candidate.id,
        details={"event": "register_candidate", "name": name, "semver": semver},
    )
    return candidate


def promote(
    db: Session,
    *,
    candidate_id: uuid.UUID,
    gate: PromotionGate,
    actor: str,
    justification: str,
) -> ModelVersion:
    """Продвинуть кандидата в ACTIVE (шаг 6). Осознанное документированное действие.

    Требует пройденного гейта и обоснования. Прежняя ACTIVE-модель уходит в RETIRED,
    но сохраняется для мгновенного отката. Само решение — за ответственным лицом.
    """
    if not gate.ok:
        raise PromotionError(
            "Продвижение запрещено, не выполнены условия: " + "; ".join(gate.reasons)
        )
    if not justification.strip():
        raise PromotionError("Требуется письменное обоснование продвижения")

    candidate = db.get(ModelVersion, candidate_id)
    if candidate is None:
        raise PromotionError("Кандидат не найден")

    previous_active = db.execute(
        select(ModelVersion).where(
            ModelVersion.name == candidate.name,
            ModelVersion.status == ModelStatus.ACTIVE,
        )
    ).scalar_one_or_none()

    if previous_active is not None:
        previous_active.status = ModelStatus.RETIRED  # сохраняется для отката

    candidate.status = ModelStatus.ACTIVE
    db.flush()

    audit.record(
        db,
        actor=actor,
        actor_role="admin",
        action=AuditAction.MODEL_PROMOTE,
        entity_type="model_version",
        entity_id=candidate.id,
        details={
            "event": "promote",
            "justification": justification,
            "previous_active": str(previous_active.id) if previous_active else None,
        },
    )
    return candidate


def rollback(
    db: Session,
    *,
    to_version_id: uuid.UUID,
    actor: str,
    reason: str,
) -> ModelVersion:
    """Мгновенный откат к предыдущей версии (FR-10, п. 6).

    Текущая ACTIVE-модель уходит в RETIRED, указанная версия становится ACTIVE.
    Не требует прохождения гейта — это аварийная операция восстановления.
    """
    target = db.get(ModelVersion, to_version_id)
    if target is None:
        raise PromotionError("Версия для отката не найдена")

    current = db.execute(
        select(ModelVersion).where(
            ModelVersion.name == target.name,
            ModelVersion.status == ModelStatus.ACTIVE,
        )
    ).scalar_one_or_none()
    if current is not None and current.id != target.id:
        current.status = ModelStatus.RETIRED

    target.status = ModelStatus.ACTIVE
    db.flush()

    audit.record(
        db,
        actor=actor,
        actor_role="admin",
        action=AuditAction.MODEL_PROMOTE,
        entity_type="model_version",
        entity_id=target.id,
        details={"event": "rollback", "reason": reason,
                 "from": str(current.id) if current else None},
    )
    return target
