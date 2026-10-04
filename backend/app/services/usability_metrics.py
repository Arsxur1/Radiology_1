"""Объективные данные юзабилити для пилота (IEC 62366; файл рисков R-01, R-03).

Файл рисков держит две опасности в зоне «снижать» на допущении, что врач действительно
проверяет черновики ИИ и не принимает их отсутствие за норму. Эти агрегаты — данные для
проверки допущения в пилоте (вместе с наблюдением и опросом, `docs/YUZABILITI.md`):

- быстрые подтверждения черновиков ИИ (быстрее FAST_CONFIRM_SECONDS после появления
  карточки на экране) — сигнал автоматического доверия (R-01);
- самостоятельное чтение: в подписанных исследованиях без черновиков ИИ врач всё же
  добавлял свои находки — отсутствие черновика не принимают за «норму» (R-03);
- время от приёма исследования до подписи заключения — сторона пользы.

Только агрегаты по всем врачам, без разбивки по сотрудникам: оценивается изделие, а не
работа врачей.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditAction, AuditLog
from app.models.imaging import Series, Study
from app.models.ml import (
    Correction,
    CorrectionType,
    Finding,
    FindingSource,
    InferenceResult,
    ModelVersion,
    Report,
)

FAST_CONFIRM_SECONDS = 3.0
# Предлагаемый критерий пилота (согласуется с врачами NCMC): быстрых подтверждений не больше.
FAST_CONFIRM_MAX_SHARE = 0.10
MIN_DECISIONS = 30          # меньше — доли не показываем как вывод


def _pct(n: int, total: int) -> float | None:
    return round(n / total, 4) if total else None


def _quantiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "median": None, "p10": None, "p90": None}
    v = sorted(values)
    q = (lambda p: v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))])
    return {"n": len(v), "median": round(statistics.median(v), 1), "p10": round(q(0.1), 1),
            "p90": round(q(0.9), 1)}


def build_usability(db: Session, *, days: int = 90, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=days)).replace(tzinfo=None)

    # Решения врача по черновикам ИИ, которые врач видел (не теневой прогон, классификатор).
    rows = db.execute(
        select(Correction.correction_type, Correction.time_spent_seconds)
        .join(Finding, Correction.finding_id == Finding.id)
        .join(InferenceResult, Finding.inference_result_id == InferenceResult.id)
        .join(ModelVersion, InferenceResult.model_version_id == ModelVersion.id)
        .where(Finding.source == FindingSource.MODEL, InferenceResult.shadow_run.is_(False),
               ModelVersion.task == "classification", Correction.created_at >= since)
    ).all()
    times: dict[str, list[float]] = {t.value: [] for t in CorrectionType}
    counts = {t.value: 0 for t in CorrectionType}
    for ctype, sec in rows:
        counts[ctype.value] += 1
        if sec is not None and sec >= 0:
            times[ctype.value].append(float(sec))
    confirm_times = times[CorrectionType.ACCEPTED.value]
    fast = sum(1 for s in confirm_times if s < FAST_CONFIRM_SECONDS)
    fast_share = _pct(fast, len(confirm_times))

    # Самостоятельное чтение: подписанные исследования с черновиками ИИ и без них.
    signed = set(db.execute(select(Report.study_id).where(Report.finalized_by.is_not(None),
                                                          Report.updated_at >= since)).scalars())
    with_drafts = set(db.execute(
        select(Series.study_id).join(Finding, Finding.series_id == Series.id)
        .join(InferenceResult, Finding.inference_result_id == InferenceResult.id)
        .join(ModelVersion, InferenceResult.model_version_id == ModelVersion.id)
        .where(Finding.source == FindingSource.MODEL, InferenceResult.shadow_run.is_(False),
               ModelVersion.task == "classification", Series.study_id.in_(signed))
    ).scalars()) if signed else set()
    with_own = set(db.execute(
        select(Series.study_id).join(Finding, Finding.series_id == Series.id)
        .where(Finding.source == FindingSource.PHYSICIAN, Series.study_id.in_(signed))
    ).scalars()) if signed else set()
    without_drafts = signed - with_drafts

    # От приёма до подписи: время первой подписи по аудиту.
    signed_at = dict(db.execute(
        select(Report.study_id, AuditLog.created_at)
        .join(AuditLog, AuditLog.entity_id == Report.id)
        .where(AuditLog.action == AuditAction.REPORT_FINALIZE, Report.study_id.in_(signed))
    ).all()) if signed else {}
    received = dict(db.execute(select(Study.id, Study.created_at).where(Study.id.in_(signed_at))).all()) \
        if signed_at else {}
    turnaround = [
        (signed_at[s].replace(tzinfo=None) - received[s].replace(tzinfo=None)).total_seconds() / 3600
        for s in signed_at if s in received and signed_at[s] and received[s]
    ]

    decisions = sum(counts.values())
    notes = []
    if decisions < MIN_DECISIONS:
        notes.append(f"Решений по черновикам ИИ {decisions} < {MIN_DECISIONS} — доли пока не вывод.")
    elif fast_share is not None and fast_share > FAST_CONFIRM_MAX_SHARE:
        notes.append(f"Быстрых подтверждений (< {FAST_CONFIRM_SECONDS:.0f} с) {fast_share:.0%} — больше "
                     f"{FAST_CONFIRM_MAX_SHARE:.0%}: возможное автоматическое доверие (R-01) — разобрать на "
                     "наблюдении в пилоте.")
    if signed and not with_drafts:
        notes.append("В подписанных исследованиях нет видимых черновиков ИИ (режим SHADOW?) — "
                     "показатели R-01 появятся в ASSIST.")
    return {
        "days": days,
        "ai_decisions": {"total": decisions, **counts},
        "decision_seconds": {k: _quantiles(v) for k, v in times.items()},
        "fast_confirm": {"threshold_seconds": FAST_CONFIRM_SECONDS, "count": fast,
                         "share": fast_share, "max_share": FAST_CONFIRM_MAX_SHARE},
        "independent_reading": {
            "signed_studies": len(signed),
            "signed_with_ai_drafts": len(with_drafts),
            "signed_without_ai_drafts": len(without_drafts),
            # Доля исследований без черновиков, где врач сам добавил находку: не ноль — врач
            # читает снимок сам. Сравнивать с долей в исследованиях с черновиками.
            "own_findings_share_without_drafts": _pct(len(without_drafts & with_own), len(without_drafts)),
            "own_findings_share_with_drafts": _pct(len(with_drafts & with_own), len(with_drafts)),
        },
        "turnaround_hours": _quantiles(turnaround),
        "notes": notes,
    }
