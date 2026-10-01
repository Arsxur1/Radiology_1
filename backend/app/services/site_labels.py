"""Метки площадки из решений врачей → обучающий манифест (FR-9 → FR-10, самообучение).

Истина врача по серии (коды словаря находок ОГК):
  - позитив: находка врача (не отклонена) или подтверждённая/изменённая находка модели;
  - негатив: находка модели, отклонённая врачом (SR-6);
  - если заключение по исследованию подписано (report.finalized_by) — врач прочёл
    снимок целиком, поэтому все прочие коды словаря для модальности = 0, а
    «без патологии» (CXR-000) = 1 при отсутствии позитивов;
  - иначе неупомянутые коды маскируются (None) — молчание врача не считается «нет».

Результаты теневого прогона в истину не входят никогда. Пиксели и PHI не
экспортируются: только псевдонимные ключи и префикс объекта в MinIO (SR-9).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imaging import Series, Study
from app.models.ml import (
    ConfirmationStatus,
    Correction,
    CorrectionType,
    Finding,
    FindingSource,
    InferenceResult,
    Report,
)
from app.services.finding_vocabulary import list_findings

SITE_DATASET = "ncmc"
NORMAL_CODE = "CXR-000"
XRAY_MODALITIES = ("CR", "DX")


@dataclass
class SeriesTruth:
    positives: set[str] = field(default_factory=set)
    negatives: set[str] = field(default_factory=set)
    finalized: bool = False


def _is_cxr(code: str | None) -> bool:
    return bool(code) and code.startswith("CXR-")


def finalized_study_ids(db: Session) -> set:
    return set(db.execute(select(Report.study_id).where(Report.finalized_by.is_not(None))).scalars())


CHUNK = 5000   # размер пакета для IN (...): и PostgreSQL, и SQLite держат такие списки


class SeriesKey(NamedTuple):
    """Минимум для истины врача — без загрузки полных объектов серии."""

    id: uuid.UUID
    study_id: uuid.UUID


def truths_for_series(db: Session, series: list, finalized: set | None = None) -> dict:
    """Истина врача сразу для многих серий: два запроса на пакет вместо двух на серию.

    На году работы клиники (десятки тысяч серий) построчная выборка занимала минуты —
    сводная панель и отчёт теневого прогона не укладывались в таймаут шлюза.
    """
    finalized = finalized_study_ids(db) if finalized is None else finalized
    out = {se.id: SeriesTruth(finalized=se.study_id in finalized) for se in series}
    ids = list(out)
    for i in range(0, len(ids), CHUNK):
        part = ids[i:i + CHUNK]
        rows = db.execute(
            select(Finding.id, Finding.series_id, Finding.code, Finding.source, Finding.confirmation_status)
            .outerjoin(InferenceResult, Finding.inference_result_id == InferenceResult.id)
            .where(Finding.series_id.in_(part))
            .where((InferenceResult.id.is_(None)) | (InferenceResult.shadow_run.is_(False)))
        ).all()
        series_of: dict = {}
        for fid, sid, code, source, status in rows:
            series_of[fid] = sid
            if not _is_cxr(code):
                continue
            truth = out[sid]
            if status == ConfirmationStatus.REJECTED:
                truth.negatives.add(code)
            elif source == FindingSource.PHYSICIAN or status == ConfirmationStatus.CONFIRMED:
                truth.positives.add(code)
        # Врач заменил код находки ИИ: исходный код — ошибка модели, т.е. негатив.
        fids = list(series_of)
        for j in range(0, len(fids), CHUNK):
            for fid, before, after in db.execute(
                select(Correction.finding_id, Correction.before, Correction.after)
                .where(Correction.finding_id.in_(fids[j:j + CHUNK]),
                       Correction.correction_type == CorrectionType.MODIFIED)
            ).all():
                old, new = (before or {}).get("code"), (after or {}).get("code")
                if _is_cxr(old) and old != new:
                    out[series_of[fid]].negatives.add(old)
    for truth in out.values():
        truth.negatives -= truth.positives
    return out


def series_truth(db: Session, series: Series, finalized: set | None = None) -> SeriesTruth:
    return truths_for_series(db, [series], finalized)[series.id]


def labels_from_truth(truth: SeriesTruth, modality: str) -> dict[str, int | None]:
    labels: dict[str, int | None] = {c: 0 for c in truth.negatives}
    labels.update({c: 1 for c in truth.positives})
    if truth.finalized:
        for concept in list_findings(modality):
            labels.setdefault(concept.code, 0)
        labels[NORMAL_CODE] = 0 if truth.positives - {NORMAL_CODE} else 1
    return labels


def _split(patient_key: str, test_fraction: float, validate_fraction: float) -> str:
    """Детерминированно по пациенту: один пациент — всегда в одной части (без утечки)."""
    u = int(hashlib.sha256(patient_key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    if u < test_fraction:
        return "test"
    if u < test_fraction + validate_fraction:
        return "validate"
    return "train"


def site_manifest(
    db: Session,
    *,
    modalities: tuple[str, ...] = XRAY_MODALITIES,
    test_fraction: float = 0.15,
    validate_fraction: float = 0.10,
) -> tuple[list[dict], dict]:
    """Записи в формате app.training.manifest.ManifestRecord + сводный отчёт."""
    finalized = finalized_study_ids(db)
    rows = db.execute(
        select(Series.id, Series.study_id, Series.modality, Series.series_instance_uid, Series.object_prefix,
               Study.patient_age_years, Study.patient_id)
        .join(Study, Series.study_id == Study.id).where(Series.modality.in_(modalities))
        # Возможен текст с данными пациента в пикселях — в обучение не идёт (SR-9).
        .where(Series.burned_in_risk.is_(False))
    ).all()
    records: list[dict] = []
    report = {"records": 0, "skipped_unlabeled": 0, "skipped_no_age": 0,
              "finalized": 0, "positives": {}, "populations": {}}
    truths = truths_for_series(db, [SeriesKey(r.id, r.study_id) for r in rows], finalized)
    for series in rows:
        truth = truths[series.id]
        labels = labels_from_truth(truth, series.modality)
        if not any(v is not None for v in labels.values()):
            report["skipped_unlabeled"] += 1
            continue
        age = series.patient_age_years
        if age is None:
            # Без возраста нельзя отнести к взрослым/детям (п. 1.2) — не используем.
            report["skipped_no_age"] += 1
            continue
        population = "pediatric" if age < 18 else "adult"
        patient_key = str(series.patient_id)
        records.append({
            "dataset": SITE_DATASET,
            "image_id": series.series_instance_uid,
            "image_path": series.object_prefix or series.series_instance_uid,
            "patient_key": patient_key,
            "split": _split(patient_key, test_fraction, validate_fraction),
            "population": population,
            "labels": dict(sorted(labels.items())),
            "view": None,
            "boxes": [],
        })
        report["records"] += 1
        report["finalized"] += int(truth.finalized)
        report["populations"][population] = report["populations"].get(population, 0) + 1
        for c in truth.positives:
            report["positives"][c] = report["positives"].get(c, 0) + 1
    return records, report
