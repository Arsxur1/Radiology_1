"""Единый манифест обучающих примеров (ТЗ, SR-5: трассируемость источника).

Каждая запись — одно изображение: откуда (датасет, путь), чей (ключ пациента для
сплитов без утечки), популяция (взрослые/дети — валидируются раздельно, п. 1.2),
метки в кодах словаря находок (1 / 0 / None — замаскировано) и рамки находок.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

ADULT = "adult"
PEDIATRIC = "pediatric"


@dataclass
class ManifestRecord:
    dataset: str
    image_id: str
    image_path: str                  # относительно корня датасета
    patient_key: str
    split: str                       # train | validate | test
    population: str                  # adult | pediatric
    labels: dict[str, int | None]    # код находки → 1 / 0 / None (маска)
    view: str | None = None
    boxes: list[dict] = field(default_factory=list)


def combine(values: list[int | None]) -> int | None:
    """Свести несколько исходных меток, указывающих на один код.

    Любая положительная → 1; иначе любая отрицательная → 0; иначе маска.
    """
    if any(v == 1 for v in values):
        return 1
    if any(v == 0 for v in values):
        return 0
    return None


def write_jsonl(records: list[ManifestRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[ManifestRecord]:
    with path.open(encoding="utf-8") as fh:
        return [ManifestRecord(**json.loads(line)) for line in fh if line.strip()]


def label_stats(records: list[ManifestRecord]) -> dict[str, dict[str, int]]:
    """Сколько положительных/отрицательных/замаскированных по каждому коду."""
    stats: dict[str, dict[str, int]] = {}
    for r in records:
        for code, v in r.labels.items():
            s = stats.setdefault(code, {"pos": 0, "neg": 0, "masked": 0})
            s["pos" if v == 1 else "neg" if v == 0 else "masked"] += 1
    return dict(sorted(stats.items()))
