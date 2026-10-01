"""Проверка рентген-модели на детях по открытому набору Guangzhou (Kermany et al., CC BY 4.0).

Набор: 5 856 рентгенов ОГК детей 1–5 лет, метки «норма» / «пневмония» (бактериальная или
вирусная — по имени файла). Метки — диагнозы, поэтому модель здесь не учится и не
выдаёт диагноз (SR-1): проверяется, как ведут себя **находки-черновики**, которые увидит
врач, на настоящих детских снимках:

- AUROC «есть ли что-то» — максимум вероятностей по кодам словаря против «пневмония»;
- доля снимков **нормы**, где появится хотя бы один черновик (лишняя работа врача);
- доля снимков **пневмонии** с хотя бы одним черновиком (не останется ли патология без
  подсказки); отдельно для бактериальной и вирусной;
- по каждому коду — AUROC и доля черновиков в норме и в пневмонии.

Выход модели «Pneumonia» — диагноз, врачу не показывается; его AUROC приводится только
для сравнения с публикациями. Наружу (в отчёт) — только агрегаты.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from app.training.metrics import auroc

CLASSES = ("normal", "bacterial", "viral", "mixed", "mycoplasma", "pneumonia")  # «pneumonia» — подтип неизвестен
# Папка-класс набора HWCMC (Hainan, Zenodo 13744272): «Pediatric Pneumonia/<класс>/<класс>_N.png».
_FOLDER_KIND = {"normal": "normal", "bacteria": "bacterial", "bacterial": "bacterial", "virus": "viral",
                "viral": "viral", "mixed": "mixed", "mycoplasma": "mycoplasma"}
CITATION = ("Kermany D., Zhang K., Goldbaum M. Labeled Optical Coherence Tomography (OCT) and Chest X-Ray "
            "Images for Classification. Mendeley Data, v2, 2018. doi:10.17632/rscbjbr9sj.2. CC BY 4.0.")


def label_of(path: str | Path) -> tuple[str, int] | None:
    """(класс, y) по пути …/NORMAL/… или …/PNEUMONIA/…_bacteria_/_virus_…"""
    p = Path(path)
    folder = p.parent.name.upper()
    name = p.name.lower()
    if folder == "NORMAL":
        return "normal", 0
    if folder == "PNEUMONIA":
        if "bacteria" in name:
            return "bacterial", 1
        if "virus" in name:
            return "viral", 1
        return "pneumonia", 1
    kind = _FOLDER_KIND.get(folder.lower())
    if kind:
        return kind, int(kind != "normal")
    return None


def find_images(root: str | Path, splits: tuple[str, ...]) -> list[tuple[Path, str, int]]:
    """Снимки выбранных частей набора (train/val/test) с метками; порядок детерминирован."""
    out = []
    for split in splits or ("",):            # без частей (HWCMC) — весь набор
        for p in sorted(Path(root).rglob(f"{split}/*/*" if split else "*/*")):
            if p.suffix.lower() in (".jpeg", ".jpg", ".png") and (lab := label_of(p)):
                out.append((p, *lab))
    return out


def npz_images(path: str | Path, splits: tuple[str, ...]):
    """Тот же набор в версии MedMNIST+ (Zenodo 10519652, CC BY 4.0): массивы 224×224,
    метки 0 — норма, 1 — пневмония (подтип не сохранён). Возвращает (массив, класс, y)."""
    import numpy as np

    data = np.load(path)
    out = []
    for split in splits:
        for img, lab in zip(data[f"{split}_images"], data[f"{split}_labels"].ravel(), strict=True):
            y = int(lab)
            out.append((img.astype("float32"), "pneumonia" if y else "normal", y))
    return out


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def _bootstrap_ci(y: list[int], s: list[float], n: int = 1000, seed: int = 7) -> tuple[float, float] | None:
    """95% доверительный интервал AUROC бутстрепом: выборка с возвращением, детерминированно."""
    rnd = random.Random(seed)
    idx = range(len(y))
    vals = []
    for _ in range(n):
        pick = [rnd.choice(idx) for _ in idx]
        v = auroc([y[i] for i in pick], [s[i] for i in pick])
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)


def summarize(records: list[dict], thresholds: dict[str, float], *, bootstrap: int = 1000) -> dict:
    """Агрегаты по записям {"kind", "y", "probs": {код: p}, "raw_pneumonia": p | None}."""
    codes = sorted(thresholds)
    y = [r["y"] for r in records]
    any_score = [max((r["probs"].get(c, 0.0) for c in codes), default=0.0) for r in records]
    drafted = [[c for c in codes if r["probs"].get(c, 0.0) >= thresholds[c]] for r in records]

    def group(kind: str | None, pos: bool | None = None) -> list[int]:
        return [i for i, r in enumerate(records)
                if (kind is None or r["kind"] == kind) and (pos is None or r["y"] == int(pos))]

    normal, pneu = group(None, False), group(None, True)
    per_code = {}
    for c in codes:
        scores = [r["probs"].get(c, 0.0) for r in records]
        per_code[c] = {
            "auroc": auroc(y, scores),
            "draft_rate_normal": _rate([c in drafted[i] for i in normal]),
            "draft_rate_pneumonia": _rate([c in drafted[i] for i in pneu]),
            "threshold": thresholds[c],
        }
    raw = [r.get("raw_pneumonia") for r in records]
    return {
        "n": {k: len(group(k)) for k in CLASSES if group(k)} | {"total": len(records)},
        "any_finding_auroc": auroc(y, any_score),
        "any_finding_auroc_ci95": _bootstrap_ci(y, any_score, bootstrap) if bootstrap else None,
        "normal_with_any_draft": _rate([bool(drafted[i]) for i in normal]),
        "normal_mean_drafts": round(sum(len(drafted[i]) for i in normal) / len(normal), 3) if normal else None,
        "pneumonia_with_any_draft": _rate([bool(drafted[i]) for i in pneu]),
        "bacterial_with_any_draft": _rate([bool(drafted[i]) for i in group("bacterial")]),
        "viral_with_any_draft": _rate([bool(drafted[i]) for i in group("viral")]),
        "with_any_draft_by_kind": {k: _rate([bool(drafted[i]) for i in group(k)]) for k in CLASSES if group(k)},
        "per_code": per_code,
        "reference_raw_pneumonia_output_auroc": auroc(y, raw) if all(v is not None for v in raw) else None,
    }


def normal_floor_thresholds(records: list[dict], thresholds: dict[str, float], max_rate: float) -> dict[str, float]:
    """Пороги, при которых каждый код рисует черновик не более чем у max_rate здоровых детей.

    Внешний набор не знает истины по находкам (только «норма/пневмония»), поэтому честно
    можно лишь ограничить ложные черновики у здоровых: порог кода поднимается до квантиля
    (1 − max_rate) его оценок на снимках нормы и **никогда не опускается** ниже исходного.
    Подбирать на одной части набора (train), проверять — на другой (test).
    """
    normals = [r for r in records if r["y"] == 0]
    out = {}
    for code, cur in thresholds.items():
        scores = sorted(r["probs"].get(code, 0.0) for r in normals)
        if not scores:
            out[code] = cur
            continue
        k = min(len(scores) - 1, int((1 - max_rate) * len(scores)))
        # Строго выше k-й оценки, с округлением вверх до 4 знаков (округление вниз пропустило бы лишних).
        above = math.floor(scores[k] * 10_000) / 10_000 + 0.0001
        out[code] = round(max(cur, above), 4)
    return out
