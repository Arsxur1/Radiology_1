"""Замороженный тестовый набор и защита от утечки (ТЗ, FR-10 п. 4).

Тест формируется ДО обучения, фиксируется контрольной суммой и не открывается
при обучении: загрузчик обучающих данных технически исключает его изображения
и всех пациентов, попавших в тест (утечка по пациенту портит оценку).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.training.manifest import ManifestRecord


class FrozenTestError(Exception):
    """Нарушение правил замороженного теста."""


@dataclass(frozen=True)
class FrozenTest:
    image_ids: frozenset[str]
    patient_keys: frozenset[str]
    digest: str


def _digest(image_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(image_ids)).encode()).hexdigest()


def freeze_test_set(records: list[ManifestRecord], out_path: Path, *, force: bool = False) -> FrozenTest:
    """Зафиксировать тест из записей со split=test. Повторное формирование запрещено."""
    if out_path.exists() and not force:
        raise FrozenTestError(
            f"Замороженный тест уже сформирован: {out_path}. Переформировать после начала "
            "обучения нельзя (FR-10 п. 4)."
        )
    test = [r for r in records if r.split == "test"]
    if not test:
        raise FrozenTestError("В манифесте нет записей split=test")
    ids = sorted({f"{r.dataset}:{r.image_id}" for r in test})
    patients = sorted({r.patient_key for r in test})
    payload = {
        "image_ids": ids,
        "patient_keys": patients,
        "digest": _digest(ids),
        "count": len(ids),
        "populations": sorted({r.population for r in test}),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return FrozenTest(frozenset(ids), frozenset(patients), payload["digest"])


def load_frozen(path: Path) -> FrozenTest:
    data = json.loads(path.read_text(encoding="utf-8"))
    if _digest(data["image_ids"]) != data["digest"]:
        raise FrozenTestError("Контрольная сумма замороженного теста не совпадает — файл изменён")
    return FrozenTest(frozenset(data["image_ids"]), frozenset(data["patient_keys"]), data["digest"])


def training_records(
    records: list[ManifestRecord], frozen: FrozenTest
) -> tuple[list[ManifestRecord], int]:
    """Отобрать train/validate, исключив тест и всех пациентов теста.

    Возвращает (записи, число исключённых из-за пересечения по пациенту).
    """
    kept: list[ManifestRecord] = []
    leaked = 0
    for r in records:
        if r.split == "test":
            continue
        if f"{r.dataset}:{r.image_id}" in frozen.image_ids:
            raise FrozenTestError(f"Изображение теста {r.image_id} попало в обучающий сплит")
        if r.patient_key in frozen.patient_keys:
            leaked += 1
            continue
        kept.append(r)
    return kept, leaked
