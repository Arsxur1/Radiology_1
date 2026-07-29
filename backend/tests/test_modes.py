"""Тесты механики режимов (ТЗ, раздел 2, 9)."""

from app.core.modes import (
    OperatingMode,
    can_transition,
    results_visible_to_physician,
)


def test_shadow_hides_results():
    # В SHADOW врач не видит ничего (раздел 2).
    assert results_visible_to_physician(OperatingMode.SHADOW) is False
    assert results_visible_to_physician(OperatingMode.RESEARCH) is True
    assert results_visible_to_physician(OperatingMode.ASSIST) is True


def test_cannot_jump_research_to_assist():
    # Нельзя миновать SHADOW: RESEARCH → ASSIST запрещён.
    assert can_transition(OperatingMode.RESEARCH, OperatingMode.ASSIST) is False
    assert can_transition(OperatingMode.RESEARCH, OperatingMode.SHADOW) is True


def test_shadow_to_assist_allowed_mechanically():
    # Механически переход возможен; критерии раздела 9 проверяются отдельно.
    assert can_transition(OperatingMode.SHADOW, OperatingMode.ASSIST) is True


def test_assist_can_rollback_to_shadow():
    # Обязателен мгновенный откат (FR-10, п. 6).
    assert can_transition(OperatingMode.ASSIST, OperatingMode.SHADOW) is True
