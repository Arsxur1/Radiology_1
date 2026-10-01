"""Кандидат из открытой предобученной модели TorchXRayVision (для теневой оценки).

Пока нет своих обученных весов (нужны GPU-сервер и данные по DUA), площадка может
начать теневой прогон на открытой модели: врачу результаты не видны, но копится
статистика расхождений с заключениями — ориентир для своих моделей.

Ограничения, которые фиксируются в карточке:
  - модели обучены в основном на взрослых (NIH, PadChest, CheXpert, MIMIC и др.) —
    для детей это ТОЛЬКО теневая оценка переносимости, не основание для ASSIST;
  - лицензии части исходных датасетов исследовательские — до клинического применения
    нужна юридическая проверка (ТЗ, вопрос 34);
  - выходы сопоставляются только с кодами словаря находок; диагнозы отбрасываются.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.training.label_map import map_labels

# Порог после нормировки op_threshs авторов модели: 0.5 = их рабочая точка (высокая
# чувствительность, много срабатываний). Для черновиков, которые увидит врач, по умолчанию
# берётся порог авторов «PPV 80%» (ppv80_thres) — меньше ложных черновиков. Дальше
# пороги калибруются по заключениям врачей площадки (services/calibration.py).
XRV_THRESHOLD = 0.5
# Нижняя граница порога: у редких классов рабочая точка авторов крошечная, и нормированная
# оценка на любом снимке держится у 0.50 — «на границе» черновик не создаётся.
XRV_MIN_THRESHOLD = 0.55


def xrv_thresholds(pathologies: list[str], ppv80: list[float] | None) -> dict[str, float]:
    """Порог по коду: ppv80 авторов (если есть), иначе 0.5; при слиянии — наименьший."""
    report = map_labels([p for p in pathologies if p])
    out: dict[str, float] = {}
    for i, p in enumerate(pathologies):
        code = report.mapped.get(p)
        if not code:
            continue
        t = XRV_MIN_THRESHOLD
        if ppv80 is not None and i < len(ppv80) and ppv80[i] == ppv80[i]:  # не NaN
            t = max(XRV_MIN_THRESHOLD, float(ppv80[i]))
        out[code] = min(out.get(code, 1.0), round(t, 4))
    return out


def xrv_codes(pathologies: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(коды словаря, исключённые диагнозы, несопоставленные выходы)."""
    report = map_labels([p for p in pathologies if p])
    return report.codes, report.excluded_diagnoses, report.unmapped


def xrv_card(
    *, weights_name: str, weights_hash: str, pathologies: list[str], description: str,
    semver: str = "0.1.0", age_min: float = 0, age_max: float | None = None,
    ppv80: list[float] | None = None,
) -> dict:
    codes, excluded, unmapped = xrv_codes(pathologies)
    thresholds = xrv_thresholds(pathologies, ppv80)
    age: dict = {"min_years": age_min}
    if age_max is not None:
        age["max_years"] = age_max
    short = weights_name.replace("densenet121-res224-", "")
    return {
        "name": f"xrv_{short}",
        "semver": semver,
        "task": "classification",
        "weights_hash": weights_hash,
        "adapter": {"type": "xrv", "weights": weights_name},
        "applicability": {
            "modality": ["CR", "DX"],
            "body_part": ["CHEST", "THORAX"],
            "age": age,
            "allow_lossy": False,
        },
        "operating_points": {c: {"threshold": thresholds[c]} for c in codes},
        "threshold_policy": "ppv80 авторов модели" if ppv80 is not None else "0.5 (рабочая точка авторов)",
        "output_codes": codes,
        "excluded_labels": excluded,
        "unmapped_outputs": unmapped,
        "source": f"TorchXRayVision {weights_name}: {description}",
        "created_at": datetime.now(UTC).isoformat(),
        "intended_use": (
            "Теневая оценка на площадке. Обучена в основном на взрослых; для детей — только "
            "измерение переносимости. До ASSIST: локальная валидация и юридическая проверка лицензий."
        ),
        "initial_status": "shadow",
    }


def registration_from_card(card: dict) -> dict:
    keys = ("name", "semver", "weights_hash", "applicability", "task", "operating_points", "adapter")
    # Происхождение данных xrv сервер определяет по весам (services/data_provenance).
    return {k: card[k] for k in keys}
