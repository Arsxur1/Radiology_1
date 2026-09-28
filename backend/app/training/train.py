"""Дообучение классификатора находок рентгена ОГК (ТЗ, FR-10 п. 3).

- Предобученная сеть (DenseNet-121, веса ImageNet) + дообучение: обучения «с нуля»
  нет (ТЗ, раздел 8).
- Выходы — только коды НАХОДОК словаря, не диагнозы (SR-1). Результаты модели
  всегда черновик для подтверждения врачом (SR-2), кандидат стартует в SHADOW.
- Неопределённые/отсутствующие метки маскируются в функции потерь.
- Аугментации без зеркального отражения: отражение подменяет сторону (situs).
- Взрослые и дети обучаются и валидируются раздельно (п. 1.2).

Тяжёлые зависимости импортируются только здесь и только на обучающем сервере:
    pip install -e ".[train]"
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

from app.training.manifest import ManifestRecord
from app.training.metrics import mean_defined, per_code_auroc
from app.training.model_card import (
    build_applicability,
    build_card,
    registration_payload,
    weights_sha256,
)
from app.training.splits import FrozenTest
from app.training.thresholds import operating_points

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def load_grayscale(path: Path, size: int):  # pragma: no cover - нужны Pillow/numpy/pydicom
    """Прочитать JPG или DICOM в нормализованное изображение size×size.

    Каталог серии (экспорт площадки) — берётся первый по имени DICOM-файл.
    """
    import numpy as np
    from PIL import Image

    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in (".dcm", ".dicom"))
        if not files:
            raise FileNotFoundError(f"В каталоге серии нет DICOM: {path}")
        path = files[0]

    if path.suffix.lower() in (".dicom", ".dcm"):
        import pydicom

        try:
            from pydicom.pixels import apply_voi_lut
        except ImportError:
            from pydicom.pixel_data_handlers.util import apply_voi_lut
        ds = pydicom.dcmread(str(path))
        arr = ds.pixel_array.astype("float32")
        try:
            arr = apply_voi_lut(arr, ds).astype("float32")
        except Exception:  # noqa: BLE001 - VOI LUT есть не во всех файлах
            pass
        if getattr(ds, "PhotometricInterpretation", "") == "MONOCHROME1":
            arr = arr.max() - arr
    else:
        arr = np.asarray(Image.open(path).convert("L"), dtype="float32")
    lo, hi = float(arr.min()), float(arr.max())
    arr = (arr - lo) / (hi - lo) if hi > lo else arr * 0
    return Image.fromarray((arr * 255).astype("uint8")).resize((size, size), Image.BILINEAR)


def _torch_dataset(records, roots, codes, size, train):  # pragma: no cover - нужен torch
    import torch
    from torchvision import transforms

    aug = [transforms.RandomAffine(degrees=5, translate=(0.03, 0.03), scale=(0.95, 1.05))] if train else []
    tf = transforms.Compose([
        *aug,
        transforms.Grayscale(num_output_channels=3),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])

    class CXRDataset(torch.utils.data.Dataset):
        def __len__(self):
            return len(records)

        def __getitem__(self, i):
            r: ManifestRecord = records[i]
            img = load_grayscale(Path(roots[r.dataset]) / r.image_path, size)
            y = torch.tensor([float(r.labels.get(c) or 0) for c in codes])
            mask = torch.tensor([0.0 if r.labels.get(c) is None else 1.0 for c in codes])
            return tf(img), y, mask

    return CXRDataset()


def _predict(model, loader, device):  # pragma: no cover - нужен torch
    import torch

    model.eval()
    scores, truths = [], []
    with torch.no_grad():
        for x, y, mask in loader:
            p = torch.sigmoid(model(x.to(device))).cpu()
            scores.extend(p.tolist())
            for row_y, row_m in zip(y.tolist(), mask.tolist(), strict=True):
                truths.append([int(v) if m else None for v, m in zip(row_y, row_m, strict=True)])
    return truths, scores


def build_backbone(pretrained: str):  # pragma: no cover - нужен torch
    """DenseNet-121: веса ImageNet из интернета, из локального файла или без них.

    - "imagenet" — скачать (нужен доступ к download.pytorch.org);
    - путь к .pth — для серверов без интернета: файл скачивается заранее
      (https://download.pytorch.org/models/densenet121-a639ec97.pth) и переносится;
    - "none" — без предобучения: ТОЛЬКО для технической проверки контура, такую модель
      не регистрировать (ТЗ исключает обучение «с нуля»; карточка это фиксирует).
    """
    import torch
    from torchvision import models

    if pretrained == "imagenet":
        return models.densenet121(weights=models.DenseNet121_Weights.DEFAULT)
    model = models.densenet121()
    if pretrained != "none":
        state = torch.load(pretrained, map_location="cpu")
        model.load_state_dict(state.get("state_dict", state) if isinstance(state, dict) else state)
    return model


def output_codes(records: list[ManifestRecord]) -> list[str]:
    """Детерминированный порядок выходов: коды, у которых есть хоть один позитив."""
    positive = {c for r in records for c, v in r.labels.items() if v == 1}
    return sorted(positive)


def train(  # pragma: no cover - нужен torch и данные на обучающем сервере
    *,
    records: list[ManifestRecord],
    frozen: FrozenTest,
    roots: dict[str, str],
    population: str,
    out_dir: Path,
    name: str,
    semver: str,
    excluded_labels: list[str],
    epochs: int = 5,
    batch_size: int = 16,
    lr: float = 1e-4,
    image_size: int = 512,
    num_workers: int = 4,
    seed: int = 42,
    age_min: float | None = None,
    age_max: float | None = None,
    pretrained: str = "imagenet",
) -> dict:
    import torch
    from torchvision import models

    random.seed(seed)
    torch.manual_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    applicability = build_applicability(population, age_min=age_min, age_max=age_max)
    train_recs = [r for r in records if r.split == "train"]
    val_recs = [r for r in records if r.split == "validate"]
    codes = output_codes(train_recs)
    if not codes or not val_recs:
        raise RuntimeError("Недостаточно данных: нет позитивных меток или валидационной выборки")

    dl = torch.utils.data.DataLoader
    train_loader = dl(_torch_dataset(train_recs, roots, codes, image_size, True),
                      batch_size=batch_size, shuffle=True, num_workers=num_workers)
    val_loader = dl(_torch_dataset(val_recs, roots, codes, image_size, False),
                    batch_size=batch_size, num_workers=num_workers)

    model = build_backbone(pretrained)
    model.classifier = torch.nn.Linear(model.classifier.in_features, len(codes))
    model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    bce = torch.nn.BCEWithLogitsLoss(reduction="none")

    out_dir.mkdir(parents=True, exist_ok=True)
    weights_path = out_dir / "model.pt"
    history, best = [], None
    for epoch in range(1, epochs + 1):
        model.train()
        total = 0.0
        for x, y, mask in train_loader:
            x, y, mask = x.to(device), y.to(device), mask.to(device)
            loss = (bce(model(x), y) * mask).sum() / mask.sum().clamp(min=1)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item()
        truths, scores = _predict(model, val_loader, device)
        per_code = per_code_auroc(codes, truths, scores)
        mean = mean_defined(per_code)
        history.append({"epoch": epoch, "train_loss": total / max(len(train_loader), 1),
                        "val_mean_auroc": mean, "val_auroc": per_code})
        if best is None or (mean or 0) > (best["val_mean_auroc"] or 0):
            best = history[-1]
            # Пороги — по валидации лучшей эпохи; хранятся вместе с весами.
            ops = operating_points(codes, truths, scores)
            torch.save({"state_dict": model.state_dict(), "codes": codes,
                        "image_size": image_size, "operating_points": ops}, weights_path)

    card = build_card(
        name=name, semver=semver, weights_hash=weights_sha256(weights_path),
        population=population, applicability=applicability, codes=codes,
        datasets=sorted({r.dataset for r in records}), excluded_labels=excluded_labels,
        metrics=best, frozen_digest=frozen.digest, operating_points=ops,
    )
    card["pretrained"] = pretrained if pretrained in ("imagenet", "none") else f"file:{Path(pretrained).name}"
    if pretrained == "none":
        card["intended_use"] = "ТЕХНИЧЕСКАЯ ПРОВЕРКА КОНТУРА. Без предобучения — не регистрировать."
    (out_dir / "model_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), "utf-8")
    # Модель без предобучения в клинику не идёт: файла для регистрации нет.
    reg_name = "registration.json" if pretrained != "none" else "registration.CHECK-ONLY.json"
    (out_dir / reg_name).write_text(
        json.dumps(registration_payload(card), ensure_ascii=False, indent=2), "utf-8")
    (out_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), "utf-8")
    return card


def evaluate_frozen(  # pragma: no cover - нужен torch
    *,
    run_dir: Path,
    records: list[ManifestRecord],
    frozen: FrozenTest,
    roots: dict[str, str],
    batch_size: int = 16,
    image_size: int = 512,
) -> dict:
    """Единственное легальное «вскрытие» замороженного теста — для гейта продвижения.

    Каждый прогон фиксируется в журнале frozen_evaluations.jsonl (кто/когда/какая модель).
    """
    import torch
    from torchvision import models

    ckpt = torch.load(run_dir / "model.pt", map_location="cpu")
    codes = ckpt["codes"]
    model = models.densenet121()
    model.classifier = torch.nn.Linear(model.classifier.in_features, len(codes))
    model.load_state_dict(ckpt["state_dict"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)

    test = [r for r in records if f"{r.dataset}:{r.image_id}" in frozen.image_ids]
    loader = torch.utils.data.DataLoader(
        _torch_dataset(test, roots, codes, image_size, False), batch_size=batch_size)
    truths, scores = _predict(model, loader, device)
    per_code = per_code_auroc(codes, truths, scores)
    result = {
        "evaluated_at": datetime.now(UTC).isoformat(),
        "weights_hash": weights_sha256(run_dir / "model.pt"),
        "frozen_digest": frozen.digest,
        "n": len(test),
        "mean_auroc": mean_defined(per_code),
        "auroc": per_code,
    }
    with (run_dir / "frozen_evaluations.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result
