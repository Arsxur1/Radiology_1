"""Режимы работы системы (ТЗ, раздел 2).

Режим задаётся на уровне установки и модальности, переключается только
администратором с записью в аудит-лог. Новая модель/клиника всегда начинает
с SHADOW; переход в ASSIST — отдельное решение (раздел 9).
"""

from __future__ import annotations

from enum import Enum


class OperatingMode(str, Enum):
    #: Всё видно, с маркировкой «не для клинического применения»
    RESEARCH = "RESEARCH"
    #: Модель работает, результаты пишутся в БД, но НЕ отображаются врачу
    SHADOW = "SHADOW"
    #: Результаты видны как черновик, требующий подтверждения (клиника)
    ASSIST = "ASSIST"


#: Видны ли результаты модели врачу в данном режиме
MODE_SHOWS_RESULTS: dict[OperatingMode, bool] = {
    OperatingMode.RESEARCH: True,
    OperatingMode.SHADOW: False,
    OperatingMode.ASSIST: True,
}

#: Разрешён ли переход между режимами напрямую.
#: Новая модель/клиника обязана пройти SHADOW перед ASSIST (раздел 9).
ALLOWED_TRANSITIONS: dict[OperatingMode, set[OperatingMode]] = {
    OperatingMode.RESEARCH: {OperatingMode.SHADOW},
    OperatingMode.SHADOW: {OperatingMode.RESEARCH, OperatingMode.ASSIST},
    OperatingMode.ASSIST: {OperatingMode.SHADOW},
}


def can_transition(current: OperatingMode, target: OperatingMode) -> bool:
    """Разрешён ли переход current → target на уровне механики режимов.

    Дополнительные критерии допуска в ASSIST (раздел 9) проверяются отдельно
    и не относятся к этому уровню.
    """
    return target in ALLOWED_TRANSITIONS.get(current, set())


def results_visible_to_physician(mode: OperatingMode) -> bool:
    return MODE_SHOWS_RESULTS[mode]
