"""Проверка рентген-модели на детских **находках** (VinDr-PCXR и другие наборы того же формата).

В детских наборах Guangzhou и HWCMC метки — диагнозы (норма/пневмония). В VinDr-PCXR врачи
разметили конкретные находки — те же коды словаря, что черновики платформы. Поэтому здесь
считается качество **по каждой находке**, доля здоровых детей с черновиком и — отдельно —
находки набора, которых модель не умеет распознавать вовсе (врач NCMC не получит по ним
черновик никогда).

Только агрегаты: ни идентификаторов снимков, ни построчных данных. Соглашение PhysioNet
(VinDr-PCXR) запрещает передавать сами данные в онлайн-ИИ-сервисы; сводный отчёт — можно.
"""

from __future__ import annotations

from app.services.shadow_eval import AGE_GROUPS, age_group
from app.training.metrics import auroc
from app.training.pediatric_eval import _bootstrap_ci, _rate

# Код «норма» — как в label_map («no finding») и в платформе (тест следит за совпадением).
NORMAL_CODE = "CXR-000"
# Находка с меньшим числом позитивов не оценивается по отдельности (AUROC неустойчив).
MIN_POSITIVES = 10


def _is_normal(labels: dict[str, int | None]) -> bool:
    findings = {c: v for c, v in labels.items() if c != NORMAL_CODE}
    if labels.get(NORMAL_CODE) == 1:
        return not any(v == 1 for v in findings.values())
    return bool(findings) and all(v == 0 for v in findings.values())


def summarize_findings(records: list[dict], thresholds: dict[str, float], *, bootstrap: int = 1000,
                       min_positives: int = MIN_POSITIVES) -> dict:
    """Агрегаты по записям {"labels": {код: 0|1|None}, "probs": {код: p}, "age": лет | None}.

    thresholds — пороги показа черновика у кандидата (коды, которые модель умеет).
    """
    model_codes = sorted(c for c in thresholds if c != NORMAL_CODE)
    dataset_codes = sorted({c for r in records for c, v in r["labels"].items() if c != NORMAL_CODE and v == 1})
    drafted = [[c for c in model_codes if r["probs"].get(c, 0.0) >= thresholds[c]] for r in records]
    any_score = [max((r["probs"].get(c, 0.0) for c in model_codes), default=0.0) for r in records]
    any_true = [int(any(v == 1 for c, v in r["labels"].items() if c != NORMAL_CODE)) for r in records]
    normal = [i for i, r in enumerate(records) if _is_normal(r["labels"])]
    abnormal = [i for i, y in enumerate(any_true) if y == 1]

    per_code = {}
    for c in model_codes:
        idx = [i for i, r in enumerate(records) if r["labels"].get(c) is not None]
        y = [records[i]["labels"][c] for i in idx]
        s = [records[i]["probs"].get(c, 0.0) for i in idx]
        pos = sum(y)
        hit = [c in drafted[i] for i in idx]
        tp = sum(1 for h, t in zip(hit, y, strict=True) if h and t == 1)
        fp = sum(1 for h, t in zip(hit, y, strict=True) if h and t == 0)
        enough = pos >= min_positives
        per_code[c] = {
            "positives": pos,
            "evaluated": enough,
            "auroc": auroc(y, s) if enough else None,
            "auroc_ci95": _bootstrap_ci(y, s, bootstrap) if enough and bootstrap else None,
            "sensitivity": round(tp / pos, 4) if pos else None,     # доля находок, где был черновик
            "ppv": round(tp / (tp + fp), 4) if tp + fp else None,   # доля верных черновиков
            "draft_rate_normal": _rate([c in drafted[i] for i in normal]),
            "threshold": thresholds[c],
        }

    by_age = {}
    for _lo, _hi, label in (*AGE_GROUPS, (0, 0, "возраст неизвестен")):
        idx = [i for i, r in enumerate(records) if age_group(r.get("age")) == label]
        if not idx:
            continue
        ys = [any_true[i] for i in idx]
        by_age[label] = {
            "n": len(idx),
            "any_finding_auroc": auroc(ys, [any_score[i] for i in idx]) if 0 < sum(ys) < len(ys) else None,
            "normal_with_any_draft": _rate([bool(drafted[i]) for i in idx if i in set(normal)]),
        }

    return {
        "n": {"total": len(records), "normal": len(normal), "abnormal": len(abnormal)},
        "any_finding_auroc": auroc(any_true, any_score),
        "any_finding_auroc_ci95": _bootstrap_ci(any_true, any_score, bootstrap) if bootstrap else None,
        "normal_with_any_draft": _rate([bool(drafted[i]) for i in normal]),
        "normal_mean_drafts": round(sum(len(drafted[i]) for i in normal) / len(normal), 3) if normal else None,
        "abnormal_with_any_draft": _rate([bool(drafted[i]) for i in abnormal]),
        "per_code": per_code,
        # Находки набора, для которых у модели нет выхода: черновика по ним не будет никогда.
        "not_covered_by_model": {c: sum(1 for r in records if r["labels"].get(c) == 1)
                                 for c in dataset_codes if c not in thresholds},
        "by_age_group": by_age,
        "min_positives": min_positives,
    }


def collect_records(root, manifest, score, *, splits=("test",), limit: int = 0, progress=None) -> list[dict]:
    """Снимки набора → записи для summarize_findings.

    manifest — записи parse_vindr; score(массив) → {код: вероятность} (модель-кандидат).
    Снимок читается так же, как при приёме в платформе (dicom_to_float: VOI LUT, MONOCHROME1);
    возраст — из PatientAge в DICOM, если он есть. Идентификаторы снимков в записи не попадают.
    """
    import io
    from pathlib import Path

    import pydicom

    from app.services.classification import dicom_to_float
    from app.workers.dicom_meta import parse_dicom_age

    chosen = [m for m in manifest if m.split in splits]
    if limit:
        chosen = chosen[:limit]
    out = []
    for i, m in enumerate(chosen, 1):
        data = (Path(root) / m.image_path).read_bytes()
        header = pydicom.dcmread(io.BytesIO(data), stop_before_pixels=True)
        out.append({"labels": dict(m.labels), "probs": score(dicom_to_float(data)),
                    "age": parse_dicom_age(getattr(header, "PatientAge", None))})
        if progress and i % 200 == 0:
            progress(i, len(chosen))
    return out
