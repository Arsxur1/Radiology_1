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


def _rates(c: dict) -> dict:
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    c["sensitivity"] = tp / (tp + fn) if tp + fn else None
    c["ppv"] = tp / (tp + fp) if tp + fp else None
    return c


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
        for c in codes:
            pred, real = c in drafted, c in truth.positives
            key = "tp" if pred and real else "fp" if pred else "fn" if real else "tn"
            per_code[c][key] += 1
            if key != "tn":
                total[key] += 1
                dev[key] += 1

    tp, fp, fn = total["tp"], total["fp"], total["fn"]
    return {
        "model_version_id": str(mv.id),
        "model": f"{mv.name}@{mv.semver}",
        "shadow_runs": shadow_runs,
        "reviewed_cases": len(seen),
        "disagreement_rate": fp / (tp + fp) if tp + fp else None,
        "miss_rate": fn / (tp + fn) if tp + fn else None,
        "per_code": {c: _rates(v) for c, v in per_code.items()},
        "per_manufacturer": {
            m: {**v, "disagreement_rate": v["fp"] / (v["tp"] + v["fp"]) if v["tp"] + v["fp"] else None,
                "miss_rate": v["fn"] / (v["tp"] + v["fn"]) if v["tp"] + v["fn"] else None}
            for m, v in sorted(per_device.items())
        },
    }
