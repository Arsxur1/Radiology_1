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
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditAction
from app.models.ml import ModelStatus, ModelVersion
from app.services import audit

MODEL_TASKS = ("segmentation", "classification")
# Открытые предобученные модели TorchXRayVision, допустимые для теневой оценки.
XRV_WEIGHTS = (
    "densenet121-res224-all", "densenet121-res224-nih", "densenet121-res224-pc",
    "densenet121-res224-chex", "densenet121-res224-mimic_nb", "densenet121-res224-mimic_ch",
)


class PromotionError(Exception):
    """Нарушение процедуры продвижения модели."""


def _validate_operating_points(ops: dict) -> None:
    """Классификатор без порогов не регистрируется: иначе нечем отсечь черновики."""
    from app.services.finding_vocabulary import by_code

    if not ops:
        raise PromotionError("Для модели классификации нужны пороги operating_points")
    for code, op in ops.items():
        if by_code(code) is None:
            raise PromotionError(f"Код {code!r} отсутствует в словаре находок")
        t = op.get("threshold") if isinstance(op, dict) else None
        if not isinstance(t, int | float) or not 0.0 < float(t) < 1.0:
            raise PromotionError(f"Порог для {code} должен быть в (0, 1)")


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
    min_shadow_cases: int = 100               # проверенных врачом случаев в теневом прогоне
    min_slice_cases: int = 20                 # срез (аппарат, возраст) оценивается от стольких случаев


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


class EvidenceError(Exception):
    """Загруженный результат замороженного теста не относится к этой модели."""


def record_frozen_evaluation(db: Session, model: ModelVersion, result: dict, *, actor: str) -> dict:
    """Сохранить результат `cli evaluate` (замороженный тест) как свидетельство гейта.

    Результат принимается, только если посчитан на весах именно этой модели: хеш весов
    из отчёта должен совпасть с зарегистрированным weights_hash (SR-5).
    """
    required = ("weights_hash", "frozen_digest", "n", "mean_auroc")
    missing = [k for k in required if k not in result]
    if missing:
        raise EvidenceError(f"В отчёте нет полей: {', '.join(missing)}")
    if result["weights_hash"] != model.weights_hash:
        raise EvidenceError("Отчёт посчитан на других весах (weights_hash не совпадает с моделью)")
    if not isinstance(result["n"], int) or result["n"] <= 0:
        raise EvidenceError("Объём замороженного теста должен быть положительным")
    frozen = {k: result.get(k) for k in (*required, "auroc", "evaluated_at")}
    model.evidence = {**(model.evidence or {}), "frozen_test": frozen}
    db.flush()
    audit.record(db, actor=actor, actor_role="admin", action=AuditAction.MODEL_PROMOTE,
                 entity_type="model_version", entity_id=model.id,
                 details={"event": "frozen_evaluation", "n": frozen["n"], "mean_auroc": frozen["mean_auroc"],
                          "frozen_digest": frozen["frozen_digest"]})
    return frozen


def _slice_problems(slices: dict, kind: str, c: PromotionCriteria) -> list[str]:
    out = []
    for name, v in (slices or {}).items():
        rate = v.get("disagreement_rate")
        if rate is None and v.get("within_tolerance") is not None:   # сегментация: объём вне допуска
            rate = 1 - v["within_tolerance"]
        if v.get("cases", v.get("n", 0)) >= c.min_slice_cases and rate is not None and rate > c.max_rejection_rate:
            out.append(f"{kind} «{name}»: доля расхождений {rate:.0%} > {c.max_rejection_rate:.0%}")
    return out


def collect_evidence(db: Session, candidate: ModelVersion, criteria: PromotionCriteria | None = None) -> dict:
    """Свидетельства для гейта — из данных платформы, а не со слов администратора.

    - замороженный тест: сохранённый отчёт evaluate на весах кандидата;
    - превосходство: средний AUROC кандидата выше действующей модели на ТОМ ЖЕ тесте;
    - теневой прогон: доля расхождений с подписанными заключениями, не меньше
      min_shadow_cases проверенных случаев;
    - деградация: срезы по аппаратам и возрастным группам детей с долей расхождений
      выше порога (срез учитывается от min_slice_cases случаев).
    """
    from app.services.shadow_eval import segmentation_shadow_report, shadow_report

    c = criteria or PromotionCriteria()
    notes: list[str] = []
    frozen = (candidate.evidence or {}).get("frozen_test") or {}
    active = db.execute(
        select(ModelVersion).where(ModelVersion.name == candidate.name, ModelVersion.task == candidate.task,
                                   ModelVersion.status == ModelStatus.ACTIVE, ModelVersion.id != candidate.id)
    ).scalars().first()
    if not frozen:
        superior = False
        notes.append("Нет результата замороженного теста для весов кандидата")
    elif active is None:
        superior = True
        notes.append("Действующей модели нет — сравнение на замороженном тесте не требуется")
    else:
        base = (active.evidence or {}).get("frozen_test") or {}
        if base.get("frozen_digest") != frozen.get("frozen_digest"):
            superior = False
            notes.append("У действующей модели нет результата на том же замороженном тесте — сравнить нельзя")
        else:
            superior = float(frozen["mean_auroc"]) > float(base["mean_auroc"])
            notes.append(f"AUROC на замороженном тесте: кандидат {frozen['mean_auroc']:.3f}, "
                         f"действующая {base['mean_auroc']:.3f}")

    if candidate.task == "segmentation":
        report = segmentation_shadow_report(db, candidate.id)
        reviewed = report["compared_series"]
        manufacturers: dict = {}
    else:
        report = shadow_report(db, candidate.id)
        reviewed = report["reviewed_cases"]
        manufacturers = report["per_manufacturer"]
    rate = report["disagreement_rate"]
    if reviewed < c.min_shadow_cases:
        notes.append(f"Теневой прогон: проверено врачом {reviewed} < {c.min_shadow_cases} случаев")
        rate = None
    problems = _slice_problems(manufacturers, "Аппарат", c) + \
        _slice_problems(report.get("per_age_group", {}), "Возрастная группа", c)
    return {
        "frozen_test_cases": int(frozen.get("n") or 0),
        "frozen_test_superior": superior,
        "shadow_rejection_rate": rate,
        "shadow_reviewed_cases": reviewed,
        "no_regression_on_new_devices": not problems,
        "slice_problems": problems,
        "notes": notes,
        "active_model": f"{active.name}@{active.semver}" if active else None,
    }


def gate_for(db: Session, candidate: ModelVersion, criteria: PromotionCriteria | None = None):
    """Гейт продвижения по свидетельствам, собранным на сервере. Возвращает (гейт, свидетельства)."""
    c = criteria or PromotionCriteria()
    ev = collect_evidence(db, candidate, c)
    gate = evaluate_promotion(
        candidate_status=candidate.status, frozen_test_cases=ev["frozen_test_cases"],
        frozen_test_superior=ev["frozen_test_superior"], shadow_rejection_rate=ev["shadow_rejection_rate"],
        no_regression_on_new_devices=ev["no_regression_on_new_devices"], criteria=c,
    )
    gate.reasons.extend(ev["slice_problems"])
    return gate, ev


def register_candidate(
    db: Session,
    *,
    name: str,
    semver: str,
    weights_hash: str,
    applicability: dict,
    actor: str,
    task: str = "segmentation",
    operating_points: dict | None = None,
    adapter: dict | None = None,
) -> ModelVersion:
    """Зарегистрировать модель-кандидата. Всегда стартует в SHADOW (раздел 2)."""
    adapter = adapter or {}
    if adapter:
        kind = adapter.get("type")
        if kind == "xrv" and task == "classification":
            if adapter.get("weights") not in XRV_WEIGHTS:
                raise PromotionError(f"Неизвестные веса xrv: {adapter.get('weights')!r}")
        elif kind == "totalsegmentator" and task == "segmentation":
            if adapter.get("task", "total") not in ("total", "total_mr"):
                raise PromotionError("Поддерживаются открытые задачи TotalSegmentator: total (КТ), total_mr (МРТ)")
        else:
            raise PromotionError("Адаптер: xrv — для классификации, totalsegmentator — для сегментации")
    if task not in MODEL_TASKS:
        raise PromotionError(f"Неизвестный тип модели {task!r}; допустимо: {', '.join(MODEL_TASKS)}")
    if task == "classification":
        _validate_operating_points(operating_points or {})
    candidate = ModelVersion(
        task=task,
        operating_points=operating_points or {},
        adapter=adapter,
        name=name,
        semver=semver,
        weights_hash=weights_hash,
        applicability=applicability,
        status=ModelStatus.SHADOW,
        installed_at=datetime.now(UTC),
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
        details={"event": "register_candidate", "name": name, "semver": semver, "task": task},
    )
    return candidate


def promote(
    db: Session,
    *,
    candidate_id: uuid.UUID,
    gate: PromotionGate,
    actor: str,
    justification: str,
    evidence: dict | None = None,
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
            # Свидетельства на момент решения — для разбора и регулятора.
            "evidence": {k: v for k, v in (evidence or {}).items() if k != "notes"},
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


def models_for(
    db: Session,
    *,
    task: str,
    modality: str | None,
    statuses: tuple[ModelStatus, ...] = (ModelStatus.ACTIVE,),
) -> list[ModelVersion]:
    """Модели заданного типа и статуса, заявленные для модальности серии.

    Пустой список модальностей в applicability трактуется как «не ограничено»;
    окончательное решение всё равно за гейтом применимости (SR-7).
    """
    rows = db.execute(
        select(ModelVersion)
        .where(ModelVersion.task == task, ModelVersion.status.in_(statuses))
        .order_by(ModelVersion.name, ModelVersion.created_at)
    ).scalars().all()
    mod = (modality or "").strip().upper()
    out = []
    for m in rows:
        allowed = [str(x).strip().upper() for x in (m.applicability or {}).get("modality", [])]
        if not allowed or mod in allowed:
            out.append(m)
    return out
