"""Проверка рентген-модели на детях: открытый набор Guangzhou (Kermany, CC BY 4.0).

    python scripts/eval_pediatric_cxr.py --data /data/kermany/chest_xray \
        --weights densenet121-res224-nih densenet121-res224-all --splits test --out report.json

Модель, предобработка, сопоставление выходов с кодами словаря и пороги — те же, что у
кандидата в платформе (classification.xrv_tensor, xrv_card). Веса берутся из кэша
TorchXRayVision или из --models-dir (файлы <sha256>.pt). В отчёт попадают только агрегаты.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, help="папка chest_xray (train/val/test → NORMAL/PNEUMONIA)")
    p.add_argument("--weights", nargs="+", default=["densenet121-res224-nih"])
    p.add_argument("--splits", nargs="+", default=["test"])
    p.add_argument("--limit", type=int, default=0, help="не больше N снимков (для проверки скрипта)")
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    import numpy as np
    import torch
    import torchxrayvision as xrv
    from PIL import Image

    from app.services.classification import xrv_code_map, xrv_tensor
    from app.training.pediatric_eval import CITATION, find_images, summarize
    from app.training.xrv import xrv_thresholds

    images = find_images(a.data, tuple(a.splits))
    if a.limit:
        images = images[: a.limit]
    if not images:
        raise SystemExit(f"Снимков не найдено в {a.data} ({a.splits})")
    torch.set_num_threads(4)
    report = {"dataset": "Pediatric CXR, Guangzhou Women and Children's Medical Center (1–5 лет)",
              "citation": CITATION, "splits": a.splits, "models": {}}
    for weights in a.weights:
        info = xrv.models.model_urls[weights]
        model = xrv.models.DenseNet(weights=weights).eval()
        pathologies = list(model.pathologies)
        codes = xrv_code_map(pathologies)
        thresholds = xrv_thresholds(pathologies, [float(x) for x in info["ppv80_thres"]]
                                    if "ppv80_thres" in info else None)
        raw_idx = pathologies.index("Pneumonia") if "Pneumonia" in pathologies else None
        records, t0 = [], time.monotonic()
        for i, (path, kind, y) in enumerate(images, 1):
            arr = np.asarray(Image.open(path).convert("L"), dtype="float32")
            with torch.no_grad():
                out = model(xrv_tensor(arr))[0].tolist()
            probs: dict[str, float] = {}
            for j, code in codes.items():
                probs[code] = max(probs.get(code, 0.0), float(out[j]))
            records.append({"kind": kind, "y": y, "probs": probs,
                            "raw_pneumonia": float(out[raw_idx]) if raw_idx is not None else None})
            if i % 200 == 0:
                print(f"{weights}: {i}/{len(images)}", flush=True)
        summary = summarize(records, thresholds, bootstrap=a.bootstrap)
        summary["seconds"] = round(time.monotonic() - t0, 1)
        report["models"][weights] = summary
        print(json.dumps({weights: {k: summary[k] for k in ("n", "any_finding_auroc", "any_finding_auroc_ci95",
                                                            "normal_with_any_draft", "pneumonia_with_any_draft")}},
                         ensure_ascii=False), flush=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(f"Отчёт: {a.out}")


if __name__ == "__main__":
    main()
