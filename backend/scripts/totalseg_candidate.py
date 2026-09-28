"""Подготовить кандидата сегментации КТ на TotalSegmentator (задача total, Apache-2.0).

    python scripts/totalseg_candidate.py --out /data/models-rw [--full] [--age-min 18]

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
    p.add_argument("--full", action="store_true", help="полное разрешение (GPU)")
    p.add_argument("--semver", default="2.0.0")
    p.add_argument("--age-min", type=float, default=18.0)
    p.add_argument("--max-slice-mm", type=float, default=5.0)
    a = p.parse_args()

    from totalsegmentator.config import get_weights_dir
    from totalsegmentator.libs import download_pretrained_weights

    from app.services.inference_adapters import TS_FAST_DATASET, TS_FULL_DATASETS, weights_fingerprint

    fast = not a.full
    ids = [297] if fast else [291, 292, 293, 294, 295]
    for i in ids:
        download_pretrained_weights(i)
    wdir = Path(get_weights_dir())
    if fast:
        h = weights_fingerprint(wdir / TS_FAST_DATASET)
    else:
        dirs = sorted(d for d in wdir.iterdir() if d.name.startswith(TS_FULL_DATASETS))
        h = "+".join(weights_fingerprint(d) for d in dirs)
    name = "totalseg_ct_fast" if fast else "totalseg_ct"
    reg = {
        "name": name, "semver": a.semver, "weights_hash": h, "task": "segmentation",
        "adapter": {"type": "totalsegmentator", "task": "total", "fast": fast},
        "operating_points": {},
        "applicability": {
            "modality": ["CT"], "body_part": ["CHEST", "THORAX", "ABDOMEN"],
            "slice_thickness_mm": {"max": a.max_slice_mm}, "age": {"min_years": a.age_min},
            "allow_lossy": False,
        },
    }
    card = {**reg, "source": "TotalSegmentator (Wasserthal et al., 2023), задача total, Apache-2.0",
            "created_at": datetime.now(UTC).isoformat(),
            "intended_use": "Структуры и объёмы органов КТ — черновик для подтверждения врачом (SR-2). "
                            "Обучена в основном на взрослых КТ; детям — только теневая оценка.",
            "initial_status": "shadow"}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reg_path = out / f"{name}-{a.semver}.registration.json"
    reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2), "utf-8")
    (out / f"{name}-{a.semver}.model_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"name": name, "weights_hash": h, "registration": str(reg_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
