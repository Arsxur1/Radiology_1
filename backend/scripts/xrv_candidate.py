"""Подготовить кандидата из открытой модели TorchXRayVision для теневого прогона.

    python scripts/xrv_candidate.py --weights densenet121-res224-all --out /data/models-rw

Скачивает веса (или берёт --file для сервера без интернета), кладёт их как
<out>/<sha256>.pt и пишет карточку и registration.json. Регистрация — вручную
админом (Администрирование → Модели → вставить registration.json) → SHADOW.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default="densenet121-res224-all")
    p.add_argument("--file", help="готовый файл весов (офлайн); иначе — скачивание")
    p.add_argument("--out", required=True)
    p.add_argument("--semver", default="0.1.0")
    p.add_argument("--age-min", type=float, default=0)
    p.add_argument("--age-max", type=float)
    a = p.parse_args()

    import torchxrayvision as xrv

    from app.training.model_card import weights_sha256
    from app.training.xrv import registration_from_card, xrv_card

    info = xrv.models.model_urls[a.weights]
    if a.file:
        src = Path(a.file)
    else:
        xrv.models.DenseNet(weights=a.weights)  # скачает в кэш библиотеки
        src = Path(xrv.utils.get_cache_dir()) / info["weights_url"].split("/")[-1]
    h = weights_sha256(src)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out / f"{h}.pt")

    card = xrv_card(weights_name=a.weights, weights_hash=h, pathologies=list(info["labels"]),
                    description=info.get("description", ""), semver=a.semver,
                    age_min=a.age_min, age_max=a.age_max,
                    ppv80=[float(x) for x in info["ppv80_thres"]] if "ppv80_thres" in info else None)
    (out / f"{card['name']}-{a.semver}.model_card.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), "utf-8")
    (out / f"{card['name']}-{a.semver}.registration.json").write_text(
        json.dumps(registration_from_card(card), ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"weights": str(out / f"{h}.pt"), "name": card["name"],
                      "codes": card["output_codes"], "excluded": card["excluded_labels"],
                      "unmapped": card["unmapped_outputs"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
