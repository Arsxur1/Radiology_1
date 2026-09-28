"""Технический запрет обучения на продуктивном контуре (ТЗ, FR-10 п. 3).

Обучающие команды требуют явного MEDVIZ_CONTOUR=training. Любое другое значение
(включая отсутствие переменной и production) — отказ. Запрет технический, а не
организационный: продуктивные контейнеры запускаются с MEDVIZ_CONTOUR=production.
"""

from __future__ import annotations

import os

TRAINING = "training"


class ContourError(RuntimeError):
    """Попытка обучения вне обучающего контура."""


def require_training_contour(env: dict[str, str] | None = None) -> None:
    value = (env if env is not None else os.environ).get("MEDVIZ_CONTOUR", "").strip().lower()
    if value != TRAINING:
        raise ContourError(
            f"Обучение запрещено на контуре {value or '<не задан>'!r}. "
            "Запускайте на отдельном обучающем сервере с MEDVIZ_CONTOUR=training (ТЗ, FR-10 п. 3)."
        )
