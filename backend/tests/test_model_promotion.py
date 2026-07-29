"""Тесты гейта продвижения моделей (ТЗ, FR-10, PCCP; раздел 9)."""

from app.models.ml import ModelStatus
from app.services.model_registry import PromotionCriteria, evaluate_promotion


def _good_evidence(**over):
    base = dict(
        candidate_status=ModelStatus.SHADOW,
        frozen_test_cases=150,
        frozen_test_superior=True,
        shadow_rejection_rate=0.05,
        no_regression_on_new_devices=True,
    )
    base.update(over)
    return base


def test_promotion_ok_when_all_criteria_met():
    gate = evaluate_promotion(**_good_evidence())
    assert gate.ok is True
    assert gate.reasons == []


def test_cannot_promote_without_shadow_run():
    # Пропуск теневого прогона (шаг 5) запрещён.
    gate = evaluate_promotion(**_good_evidence(candidate_status=ModelStatus.RETIRED))
    assert gate.ok is False
    assert any("SHADOW" in r for r in gate.reasons)


def test_frozen_test_too_small_blocks():
    gate = evaluate_promotion(**_good_evidence(frozen_test_cases=10))
    assert gate.ok is False
    assert any("Замороженный тест" in r for r in gate.reasons)


def test_high_rejection_rate_blocks():
    gate = evaluate_promotion(**_good_evidence(shadow_rejection_rate=0.30))
    assert gate.ok is False
    assert any("отклонений" in r for r in gate.reasons)


def test_regression_on_new_devices_blocks():
    # Раздел 9, п. 3: деградация на новых аппаратах недопустима.
    gate = evaluate_promotion(**_good_evidence(no_regression_on_new_devices=False))
    assert gate.ok is False
    assert any("деград" in r.lower() for r in gate.reasons)


def test_missing_shadow_data_blocks():
    gate = evaluate_promotion(**_good_evidence(shadow_rejection_rate=None))
    assert gate.ok is False


def test_not_superior_blocks():
    gate = evaluate_promotion(**_good_evidence(frozen_test_superior=False))
    assert gate.ok is False


def test_custom_criteria_thresholds():
    # Пороги согласуются под площадку (раздел 9): проверяем, что они применяются.
    strict = PromotionCriteria(min_frozen_test_cases=500)
    gate = evaluate_promotion(**_good_evidence(frozen_test_cases=200), criteria=strict)
    assert gate.ok is False
