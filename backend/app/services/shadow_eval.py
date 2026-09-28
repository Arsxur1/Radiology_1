"""Сравнение теневого прогона кандидата с решениями врачей (FR-10 п. 5).

Учитываются только серии с подписанным заключением: там врач прочёл снимок
целиком, и «не упомянул» = «нет» (см. site_labels). По каждому коду — TP/FP/FN/TN,
чувствительность и PPV. Для гейта продвижения:
  - disagreement_rate = FP / (TP + FP) — доля черновиков, которые врач не включил бы
    в заключение (оценка доли отклонений, shadow_rejection_rate);
  - miss_rate = FN / (TP + FN) — доля находок врача, пропущенных моделью.
Метрики по производителю аппарата — для проверки деградации на новых аппаратах (раздел 9).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imaging import Series, Study
from app.models.ml import InferenceResult, ModelVersion
from app.services.site_labels import NORMAL_CODE, finalized_study_ids, series_truth

AGE_GROUPS = ((0, 1, "0–1 год"), (1, 5, "1–5 лет"), (5, 12, "5–12 лет"), (12, 18, "12–18 лет"),
              (18, 200, "взрослые"))


def age_group(age: float | None) -> str:
    if age is None:
        return "возраст неизвестен"
    for lo, hi, label in AGE_GROUPS:
        if lo <= age < hi:
            return label
    return "возраст неизвестен"


def _rates(c: dict) -> dict:
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    c["sensitivity"] = tp / (tp + fn) if tp + fn else None
    c["ppv"] = tp / (tp + fp) if tp + fp else None
    return c


def _slice(v: dict) -> dict:
    return {**v, "disagreement_rate": v["fp"] / (v["tp"] + v["fp"]) if v["tp"] + v["fp"] else None,
            "miss_rate": v["fn"] / (v["tp"] + v["fn"]) if v["tp"] + v["fn"] else None}


def shadow_report(db: Session, model_version_id: uuid.UUID) -> dict:
    mv = db.get(ModelVersion, model_version_id)
    if mv is None:
        raise LookupError("Версия модели не найдена")
    codes = sorted(c for c in (mv.operating_points or {}) if c != NORMAL_CODE)
    finalized = finalized_study_ids(db)
    rows = db.execute(
        select(InferenceResult, Series, Study)
        .join(Series, InferenceResult.series_id == Series.id)
        .join(Study, Series.study_id == Study.id)
        .where(InferenceResult.model_version_id == mv.id, InferenceResult.shadow_run.is_(True))
        .order_by(InferenceResult.created_at)
    ).all()

    per_code = {c: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for c in codes}
    per_device: dict[str, dict] = {}
    per_age: dict[str, dict] = {}
    seen: set = set()
    total = {"tp": 0, "fp": 0, "fn": 0}
    shadow_runs = len(rows)
    for inference, series, study in rows:
        if series.id in seen or study.id not in finalized:
            continue  # один результат на серию (прогоны детерминированы) и только подписанные
        seen.add(series.id)
        truth = series_truth(db, series, finalized)
        drafted = set((inference.metrics or {}).get("drafted", []))
        dev = per_device.setdefault(study.manufacturer or "неизвестно", {"cases": 0, "tp": 0, "fp": 0, "fn": 0})
        dev["cases"] += 1
        grp = per_age.setdefault(age_group(study.patient_age_years), {"cases": 0, "tp": 0, "fp": 0, "fn": 0})
        grp["cases"] += 1
        for c in codes:
            pred, real = c in drafted, c in truth.positives
            key = "tp" if pred and real else "fp" if pred else "fn" if real else "tn"
            per_code[c][key] += 1
            if key != "tn":
                total[key] += 1
                dev[key] += 1
                grp[key] += 1

    tp, fp, fn = total["tp"], total["fp"], total["fn"]
    return {
        "model_version_id": str(mv.id),
        "model": f"{mv.name}@{mv.semver}",
        "shadow_runs": shadow_runs,
        "reviewed_cases": len(seen),
        "disagreement_rate": fp / (tp + fp) if tp + fp else None,
        "miss_rate": fn / (tp + fn) if tp + fn else None,
        "per_code": {c: _rates(v) for c, v in per_code.items()},
        "per_manufacturer": {m: _slice(v) for m, v in sorted(per_device.items())},
        # Переносимость на детей: взрослые модели на педиатрии проверяются здесь (раздел 9).
        "per_age_group": {g: _slice(per_age[g]) for _, _, g in (*AGE_GROUPS, (0, 0, "возраст неизвестен"))
                          if g in per_age},
    }


def segmentation_shadow_report(db: Session, model_version_id: uuid.UUID, tolerance: float = 0.10) -> dict:
    """Теневой прогон сегментации: объёмы кандидата против объёмов, принятых врачом.

    Эталон — находки той же серии со структурой того же ключа, которые врач подтвердил
    или исправил (не теневые). Метрика — относительная ошибка объёма и доля случаев в
    пределах tolerance (по умолчанию 10%), по каждой структуре и по возрастным группам.
    """
    from statistics import median

    from app.models.ml import ConfirmationStatus, Finding

    mv = db.get(ModelVersion, model_version_id)
    if mv is None:
        raise LookupError("Версия модели не найдена")
    rows = db.execute(
        select(InferenceResult, Series, Study)
        .join(Series, InferenceResult.series_id == Series.id)
        .join(Study, Series.study_id == Study.id)
        .where(InferenceResult.model_version_id == mv.id, InferenceResult.shadow_run.is_(True))
    ).all()

    errors: dict[str, list[float]] = {}
    by_age: dict[str, list[float]] = {}
    compared_series: set = set()
    for inference, series, study in rows:
        reference = {}
        for f in db.execute(
            select(Finding)
            .outerjoin(InferenceResult, Finding.inference_result_id == InferenceResult.id)
            .where(Finding.series_id == series.id,
                   Finding.confirmation_status == ConfirmationStatus.CONFIRMED,
                   (InferenceResult.id.is_(None)) | (InferenceResult.shadow_run.is_(False)))
        ).scalars():
            key = (f.coordinates or {}).get("structure_key")
            vol = (f.measurements or {}).get("volume_ml")
            if key and isinstance(vol, int | float) and vol > 0:
                reference[key] = float(vol)
        for f in db.execute(select(Finding).where(Finding.inference_result_id == inference.id)).scalars():
            key = (f.coordinates or {}).get("structure_key")
            vol = (f.measurements or {}).get("volume_ml")
            if key in reference and isinstance(vol, int | float):
                err = abs(float(vol) - reference[key]) / reference[key]
                errors.setdefault(key, []).append(err)
                by_age.setdefault(age_group(study.patient_age_years), []).append(err)
                compared_series.add(series.id)

    def summary(values: list[float]) -> dict:
        return {"n": len(values), "median_rel_error": round(median(values), 4),
                "within_tolerance": round(sum(v <= tolerance for v in values) / len(values), 4)}

    all_errors = [e for v in errors.values() for e in v]
    return {
        "model_version_id": str(mv.id),
        "model": f"{mv.name}@{mv.semver}",
        "task": "segmentation",
        "tolerance": tolerance,
        "shadow_runs": len(rows),
        "compared_series": len(compared_series),
        "overall": summary(all_errors) if all_errors else None,
        # Доля структур, где объём кандидата вышел за допуск, — аналог доли отклонений для гейта.
        "disagreement_rate": round(1 - summary(all_errors)["within_tolerance"], 4) if all_errors else None,
        "per_structure": {k: summary(v) for k, v in sorted(errors.items())},
        "per_age_group": {g: summary(by_age[g]) for _, _, g in (*AGE_GROUPS, (0, 0, "возраст неизвестен"))
                          if g in by_age},
    }
