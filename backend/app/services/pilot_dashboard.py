"""Сводная панель пилота (раздел 9 ТЗ, FR-9, FR-10, FR-11): видимый прогресс без PHI.

Только агрегаты: число исследований, решений врачей, отказов ИИ, готовность обучающих
данных и расхождения кандидатов в теневом прогоне. Никаких идентификаторов пациентов.
Недели — ISO (понедельник), считаются в Python: одинаково на PostgreSQL и SQLite.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.imaging import Series, Study
from app.models.ml import (
    AiRefusal,
    ConfirmationStatus,
    Correction,
    CorrectionType,
    Finding,
    FindingSource,
    InferenceResult,
    ModelStatus,
    ModelVersion,
    Report,
)
from app.services.corrections import REJECT_REASONS
from app.services.finding_vocabulary import by_code
from app.services.shadow_eval import shadow_report
from app.services.site_labels import site_manifest


def _week(ts: datetime | date) -> str:
    d = ts.date() if isinstance(ts, datetime) else ts
    return (d - timedelta(days=d.weekday())).isoformat()


def _weeks(now: datetime, n: int) -> list[str]:
    start = now.date() - timedelta(days=now.date().weekday())
    return [(start - timedelta(weeks=i)).isoformat() for i in range(n - 1, -1, -1)]


def _weekly(stamps, weeks: list[str]) -> list[int]:
    c = Counter(_week(t) for t in stamps if t is not None)
    return [c.get(w, 0) for w in weeks]


def _reason_kind(reason: str) -> str:
    """Группа причины отказа для сводки (текст причин — из гейта применимости)."""
    r = reason.lower()
    for key, label in (("возраст", "возраст"), ("модальн", "модальность"), ("област", "область"),
                       ("толщин", "толщина среза"), ("производ", "аппарат"), ("сжат", "сжатие"),
                       ("контраст", "контраст")):
        if key in r:
            return label
    return "другое"


def build_dashboard(db: Session, *, weeks: int = 12, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    wk = _weeks(now, weeks)

    studies = db.execute(select(Study.created_at, Study.patient_age_years, Study.modality)).all()
    ages = [a for _, a, _ in studies]
    corrections = db.execute(select(Correction.created_at, Correction.correction_type)).all()
    finalized = db.execute(select(Report.updated_at).where(Report.finalized_by.is_not(None))).scalars().all()
    refusals = db.execute(select(AiRefusal.created_at, AiRefusal.reasons)).all()

    visible_model = (
        select(Finding.confirmation_status, func.count())
        .join(InferenceResult, Finding.inference_result_id == InferenceResult.id)
        .join(ModelVersion, InferenceResult.model_version_id == ModelVersion.id)
        # Только находки классификатора: структуры сегментации — не «черновики находок».
        .where(Finding.source == FindingSource.MODEL, InferenceResult.shadow_run.is_(False),
               ModelVersion.task == "classification")
        .group_by(Finding.confirmation_status)
    )
    drafts = {s.value: n for s, n in db.execute(visible_model).all()}
    decided = drafts.get(ConfirmationStatus.CONFIRMED.value, 0) + drafts.get(ConfirmationStatus.REJECTED.value, 0)
    physician_added = db.execute(
        select(func.count()).select_from(Finding).where(Finding.source == FindingSource.PHYSICIAN)
    ).scalar_one()

    reasons = Counter(_reason_kind(r) for _, rs in refusals for r in (rs or []))
    # Почему врачи отклоняют находки ИИ (SR-6): ложные срабатывания vs артефакты vs
    # неверный код — разные задачи для следующей версии модели.
    rejected = db.execute(select(Correction.after).where(
        Correction.correction_type == CorrectionType.REJECTED)).scalars().all()
    reject_reasons = Counter(REJECT_REASONS.get((a or {}).get("reject_reason"), "причина не указана")
                             for a in rejected)
    manifest_records, manifest_report = site_manifest(db)

    shadow_models = db.execute(
        select(ModelVersion).where(ModelVersion.status == ModelStatus.SHADOW,
                                   ModelVersion.task == "classification")
    ).scalars().all()
    shadow = []
    for mv in shadow_models:
        rep = shadow_report(db, mv.id)
        shadow.append({k: rep[k] for k in ("model_version_id", "model", "shadow_runs", "reviewed_cases",
                                           "disagreement_rate", "miss_rate")})

    by_modality = Counter(m for _, _, m in studies)
    series_by_modality = Counter(db.execute(select(Series.modality)).scalars().all())
    return {
        "generated_at": now.isoformat(),
        "weeks": wk,
        "totals": {
            "studies": len(studies),
            "pediatric_studies": sum(1 for a in ages if a is not None and a < 18),
            "adult_studies": sum(1 for a in ages if a is not None and a >= 18),
            "studies_without_age": sum(1 for a in ages if a is None),
            "studies_by_modality": dict(sorted(by_modality.items())),
            "series_by_modality": dict(sorted(series_by_modality.items())),
            "reports_finalized": len(finalized),
            "physician_decisions": len(corrections),
            "physician_added_findings": physician_added,
            "ai_refusals": len(refusals),
        },
        "weekly": {
            "studies": _weekly((t for t, _, _ in studies), wk),
            "physician_decisions": _weekly((t for t, _ in corrections), wk),
            "reports_finalized": _weekly(finalized, wk),
            "ai_refusals": _weekly((t for t, _ in refusals), wk),
        },
        "ai_drafts": {
            "pending": drafts.get(ConfirmationStatus.PENDING.value, 0),
            "confirmed": drafts.get(ConfirmationStatus.CONFIRMED.value, 0),
            "rejected": drafts.get(ConfirmationStatus.REJECTED.value, 0),
            # Доля принятых врачом среди решённых черновиков (подтверждение или правка).
            "acceptance_rate": drafts.get(ConfirmationStatus.CONFIRMED.value, 0) / decided if decided else None,
            "corrections_by_type": dict(sorted(Counter(t.value for _, t in corrections).items())),
        },
        "refusal_reasons": dict(reasons.most_common()),
        "reject_reasons": dict(reject_reasons.most_common()),
        "training_data": {
            "records": manifest_report["records"],
            "populations": manifest_report["populations"],
            "finalized": manifest_report["finalized"],
            "skipped_no_age": manifest_report["skipped_no_age"],
            "positives": [
                {"code": c, "label": (by_code(c).label_ru if by_code(c) else c), "count": n}
                for c, n in sorted(manifest_report["positives"].items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            "splits": dict(sorted(Counter(r["split"] for r in manifest_records).items())),
        },
        "shadow_models": shadow,
    }
