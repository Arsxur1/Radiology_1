"""Калибровка порогов по заключениям врачей площадки (самообучение без GPU, FR-10).

Модель пишет вероятности по всем кодам в inference_result (и в теневом прогоне тоже),
а врачи подписывают заключения. По этим парам подбирается порог по индексу Юдена —
под аппараты, популяцию и манеру описания конкретной площадки.

Правила (PCCP):
  - используются только исследования с подписанным заключением;
  - пациенты тестовой части (детерминированный сплит по пациенту) в подбор НЕ входят —
    на них потом честно сравниваются старая и новая версии;
  - код меняет порог, только если есть не меньше min_pos позитивов и min_neg негативов;
  - результат — НОВЫЙ кандидат (версия +1) в SHADOW; действующая модель не меняется (SR-3).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditAction
from app.models.imaging import Series, Study
from app.models.ml import InferenceResult, ModelVersion
from app.services import audit, model_registry
from app.services.site_labels import NORMAL_CODE, SeriesKey, _split, finalized_study_ids, truths_for_series
from app.training.thresholds import youden_threshold


def calibration_proposal(
    db: Session, model_version_id: uuid.UUID, *, min_pos: int = 5, min_neg: int = 5,
) -> dict:
    mv = db.get(ModelVersion, model_version_id)
    if mv is None:
        raise LookupError("Версия модели не найдена")
    current = mv.operating_points or {}
    codes = sorted(c for c in current if c != NORMAL_CODE)
    finalized = finalized_study_ids(db)
    rows = db.execute(
        select(InferenceResult.metrics, Series.id, Study.id, Study.patient_id)
        .join(Series, InferenceResult.series_id == Series.id)
        .join(Study, Series.study_id == Study.id)
        .where(InferenceResult.model_version_id == mv.id)
        .order_by(InferenceResult.created_at)
    ).all()

    # Истина врача — одним пакетом по всем сериям с подписанным заключением.
    truth_by_series = truths_for_series(
        db, list({r[1]: SeriesKey(r[1], r[2]) for r in rows if r[2] in finalized}.values()), finalized)
    # Калибровка порогов — тоже обучение на данных площадки: отзыв согласия исключает пациента.
    from app.services.patient_admin import training_excluded_patient_ids

    excluded = training_excluded_patient_ids(db)
    seen: set = set()
    held_out = 0
    truths: dict[str, list[int]] = {c: [] for c in codes}
    scores: dict[str, list[float]] = {c: [] for c in codes}
    for metrics, series_id, study_id, patient_id in rows:
        if series_id in seen or study_id not in finalized or patient_id in excluded:
            continue
        seen.add(series_id)
        if _split(str(patient_id), 0.15, 0.10) == "test":
            held_out += 1
            continue
        probs = (metrics or {}).get("probabilities", {})
        positives = truth_by_series[series_id].positives
        for c in codes:
            if c in probs:
                truths[c].append(1 if c in positives else 0)
                scores[c].append(float(probs[c]))

    per_code: dict[str, dict] = {}
    proposed: dict[str, dict] = {}
    for c in codes:
        cur = float(current[c]["threshold"])
        n_pos = sum(truths[c])
        n_neg = len(truths[c]) - n_pos
        entry = {"current": cur, "proposed": cur, "n_pos": n_pos, "n_neg": n_neg, "changed": False}
        if n_pos >= min_pos and n_neg >= min_neg:
            op = youden_threshold(truths[c], scores[c])
            if op is not None and 0.0 < op["threshold"] < 1.0:
                entry.update(proposed=round(op["threshold"], 4), sensitivity=op["sensitivity"],
                             specificity=op["specificity"], changed=round(op["threshold"], 4) != cur)
        per_code[c] = entry
        proposed[c] = {"threshold": entry["proposed"]}
    if NORMAL_CODE in current:
        proposed[NORMAL_CODE] = current[NORMAL_CODE]
    return {
        "model": f"{mv.name}@{mv.semver}",
        "calibration_cases": len(seen) - held_out,
        "held_out_test_cases": held_out,
        "min_pos": min_pos,
        "min_neg": min_neg,
        "changed_codes": sorted(c for c, e in per_code.items() if e["changed"]),
        "per_code": per_code,
        "operating_points": proposed,
    }


def _next_semver(db: Session, name: str, semver: str) -> str:
    major, minor, patch = (int(x) for x in (semver.split(".") + ["0", "0"])[:3])
    taken = set(db.execute(select(ModelVersion.semver).where(ModelVersion.name == name)).scalars())
    patch += 1
    while f"{major}.{minor}.{patch}" in taken:
        patch += 1
    return f"{major}.{minor}.{patch}"


class CalibrationError(Exception):
    pass


def register_calibrated(db: Session, model_version_id: uuid.UUID, *, actor: str, **kw) -> ModelVersion:
    proposal = calibration_proposal(db, model_version_id, **kw)
    if not proposal["changed_codes"]:
        raise CalibrationError("Недостаточно подписанных случаев для изменения порогов")
    mv = db.get(ModelVersion, model_version_id)
    candidate = model_registry.register_candidate(
        db, name=mv.name, semver=_next_semver(db, mv.name, mv.semver), weights_hash=mv.weights_hash,
        applicability=mv.applicability, actor=actor, task=mv.task,
        operating_points=proposal["operating_points"], adapter=mv.adapter or {},
    )
    audit.record(
        db, actor=actor, actor_role="admin", action=AuditAction.MODEL_PROMOTE,
        entity_type="model_version", entity_id=candidate.id,
        details={"event": "site_calibration", "from": str(mv.id), "changed": proposal["changed_codes"],
                 "cases": proposal["calibration_cases"], "held_out": proposal["held_out_test_cases"]},
    )
    return candidate
