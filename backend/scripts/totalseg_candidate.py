"""Подготовить кандидата сегментации КТ на TotalSegmentator (задача total, Apache-2.0).

    python scripts/totalseg_candidate.py --out /data/models-rw [--task total|total_mr] [--full] [--age-min 18]

Скачивает веса (однократный прогон на встроенном примере), считает отпечаток каталога
весов (SR-5) и пишет registration.json → Администрирование → Модели → SHADOW.
--fast (по умолчанию): сетка 3 мм, ~1 мин на КТ на CPU. --full: 1.5 мм, нужен GPU.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--task", default="total", choices=["total", "total_mr"], help="total — КТ, total_mr — МРТ")
    p.add_argument("--full", action="store_true", help="полное разрешение (GPU)")
    p.add_argument("--semver", default="2.0.0")
    p.add_argument("--age-min", type=float, default=18.0)
    p.add_argument("--max-slice-mm", type=float)
    a = p.parse_args()

    from totalsegmentator.config import get_weights_dir
    from totalsegmentator.libs import download_pretrained_weights

    from app.services.inference_adapters import TS_TASKS, ts_fingerprint

    fast = not a.full
    spec = TS_TASKS[a.task]
    for i in spec["fast" if fast else "full"]:
        download_pretrained_weights(i)
    h = ts_fingerprint(get_weights_dir(), a.task, fast)
    modality = spec["modality"]
    name = f"totalseg_{'ct' if modality == 'CT' else 'mr'}{'_fast' if fast else ''}"
    body = ["CHEST", "THORAX", "ABDOMEN"] + (["BRAIN", "HEAD"] if modality == "MR" else [])
    max_slice = a.max_slice_mm or (5.0 if modality == "CT" else 8.0)
    reg = {
        "name": name, "semver": a.semver, "weights_hash": h, "task": "segmentation",
        "adapter": {"type": "totalsegmentator", "task": a.task, "fast": fast},
        "operating_points": {},
        "applicability": {
            "modality": [modality], "body_part": body,
            "slice_thickness_mm": {"max": max_slice}, "age": {"min_years": a.age_min},
            "allow_lossy": False,
        },
    }
    card = {**reg, "source": f"TotalSegmentator (Wasserthal et al.), задача {a.task}, Apache-2.0",
            "created_at": datetime.now(UTC).isoformat(),
            "intended_use": "Структуры и объёмы органов — черновик для подтверждения врачом (SR-2). "
                            "Обучена в основном на взрослых; детям — только теневая оценка.",
            "initial_status": "shadow"}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reg_path = out / f"{name}-{a.semver}.registration.json"
    reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2), "utf-8")
    (out / f"{name}-{a.semver}.model_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"name": name, "weights_hash": h, "registration": str(reg_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
