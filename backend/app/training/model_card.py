"""Карточка модели и данные для регистрации кандидата (ТЗ, FR-10, SR-5, SR-7).

Карточка фиксирует происхождение (датасеты, лицензии), порядок выходов (коды
находок), исключённые метки, метрики и границы применимости. Из неё строится
запрос регистрации кандидата: POST /models/candidates — модель стартует в SHADOW.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from app.training.manifest import ADULT, PEDIATRIC


class CardError(Exception):
    """Недостаточно данных для корректных границ применимости."""


def weights_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_applicability(
    population: str,
    *,
    age_min: float | None = None,
    age_max: float | None = None,
    modalities: tuple[str, ...] = ("CR", "DX"),
) -> dict:
    """Границы применимости по популяции обучения (взрослые/дети раздельно, п. 1.2).

    Для педиатрии возрастной диапазон задаётся явно — молча выдумывать его нельзя.
    Сжатие с потерями на входе запрещено; список аппаратов не задаётся, т.к.
    аппараты площадки в обучение не входили — это проверяется в SHADOW (раздел 9 п. 3).
    """
    age: dict[str, float] = {}
    if population == ADULT:
        age["min_years"] = age_min if age_min is not None else 18
        if age_max is not None:
            age["max_years"] = age_max
    elif population == PEDIATRIC:
        if age_max is None:
            raise CardError("Для педиатрической модели укажите явный верхний возраст (--age-max)")
        age["min_years"] = age_min if age_min is not None else 0
        age["max_years"] = age_max
    else:
        raise CardError(f"Неизвестная популяция {population!r}")
    return {
        "modality": list(modalities),
        "body_part": ["CHEST", "THORAX"],
        "age": age,
        "allow_lossy": False,
    }


def build_card(
    *,
    name: str,
    semver: str,
    weights_hash: str,
    population: str,
    applicability: dict,
    codes: list[str],
    datasets: list[str],
    excluded_labels: list[str],
    metrics: dict,
    frozen_digest: str,
    operating_points: dict[str, dict] | None = None,
) -> dict:
    return {
        "task": "classification",
        "name": name,
        "semver": semver,
        "weights_hash": weights_hash,
        "population": population,
        "applicability": applicability,
        "output_codes": codes,
        "datasets": datasets,
        "excluded_labels": excluded_labels,
        "metrics_validate": metrics,
        # Пороги по валидации: ниже порога находка-черновик не создаётся.
        "operating_points": operating_points or {},
        "frozen_test_digest": frozen_digest,
        "created_at": datetime.now(UTC).isoformat(),
        "intended_use": "Находки-черновики для подтверждения врачом; не диагноз (SR-1).",
        "initial_status": "shadow",
    }


def registration_payload(card: dict) -> dict:
    """Тело запроса POST /models/candidates (кандидат стартует в SHADOW)."""
    return {
        "name": card["name"],
        "semver": card["semver"],
        "weights_hash": card["weights_hash"],
        "applicability": card["applicability"],
        "task": card.get("task", "classification"),
        "operating_points": {c: {"threshold": op["threshold"]} for c, op in card.get("operating_points", {}).items()},
    }
