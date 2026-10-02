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
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", help="папка набора: chest_xray (Mendeley) или «Pediatric Pneumonia» (HWCMC)")
    src.add_argument("--npz", help="pneumoniamnist_224.npz (MedMNIST+, Zenodo 10519652) — тот же набор, 224×224")
    p.add_argument("--weights", nargs="+", default=["densenet121-res224-nih"])
    p.add_argument("--splits", nargs="*", default=["test"], help="части набора; без значений — весь набор (HWCMC)")
    p.add_argument("--limit", type=int, default=0, help="не больше N снимков (для проверки скрипта)")
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--calibrate-split", help="часть для подбора порогов по здоровым детям (напр. train); "
                   "оценка — на --splits")
    p.add_argument("--apply-calibration", help="отчёт с normal_floor_calibration (другого набора): применить его "
                   "пороги без изменений — внешняя проверка калибровки")
    p.add_argument("--normal-rate", type=float, nargs="+", default=[0.01, 0.02, 0.05],
                   help="допустимая доля здоровых детей с черновиком по каждому коду")
    p.add_argument("--out", required=True)
    p.add_argument("--dataset-name", default="Pediatric CXR, Guangzhou Women and Children's Medical Center (1–5 лет)")
    p.add_argument("--citation", help="цитирование набора для отчёта (по умолчанию — Guangzhou/Kermany)")
    a = p.parse_args()

    import numpy as np
    import torch
    import torchxrayvision as xrv
    from PIL import Image

    from app.services.classification import xrv_code_map, xrv_tensor
    from app.training.pediatric_eval import CITATION, find_images, normal_floor_thresholds, npz_images, summarize
    from app.training.xrv import xrv_thresholds

    def load(splits):
        imgs = npz_images(a.npz, tuple(splits)) if a.npz else find_images(a.data, tuple(splits))
        return imgs[: a.limit] if a.limit else imgs

    images = load(a.splits)
    calib_images = load([a.calibrate_split]) if a.calibrate_split else []
    if not images:
        raise SystemExit(f"Снимков не найдено в {a.data} ({a.splits})")
    torch.set_num_threads(4)
    p_name = a.dataset_name
    report = {"kind": "external_pediatric", "dataset": p_name,
              "citation": a.citation or CITATION, "splits": a.splits, "models": {},
              "source": "MedMNIST+ pneumoniamnist_224 (Zenodo 10519652, CC BY 4.0; уменьшено до 224×224 "
                        "авторами MedMNIST, подтип пневмонии не сохранён)" if a.npz else f"папка {Path(a.data).name}"}
    # Предобработка не зависит от весов: один раз на снимок (float32, как у врача; ~1 ГБ на 5 600 снимков).
    tensor_cache: dict = {}
    for weights in a.weights:
        info = xrv.models.model_urls[weights]
        model = xrv.models.DenseNet(weights=weights).eval()
        # Хеш файла весов — тот же, что у кандидата в платформе (xrv_candidate): по нему
        # отчёт принимается как свидетельство именно для этой модели.
        from app.training.model_card import weights_sha256

        wfile = Path(xrv.utils.get_cache_dir()) / info["weights_url"].split("/")[-1]
        weights_hash = weights_sha256(wfile) if wfile.exists() else None
        pathologies = list(model.pathologies)
        codes = xrv_code_map(pathologies)
        thresholds = xrv_thresholds(pathologies, [float(x) for x in info["ppv80_thres"]]
                                    if "ppv80_thres" in info else None)
        raw_idx = pathologies.index("Pneumonia") if "Pneumonia" in pathologies else None
        t0 = time.monotonic()

        def infer(imgs, tag, model=model, codes=codes, raw_idx=raw_idx, weights=weights):
            recs = []
            for i, (src_img, kind, y) in enumerate(imgs, 1):
                key = (tag, i) if a.npz else str(src_img)
                if key not in tensor_cache:
                    if a.npz:
                        arr = src_img
                    else:
                        im = Image.open(src_img)
                        # 16-битные PNG — без потери диапазона; цветные (HWCMC — RGB) — в яркость.
                        arr = np.asarray(im if im.mode in ("I", "I;16", "F") else im.convert("L"), dtype="float32")
                    tensor_cache[key] = xrv_tensor(arr)
                with torch.no_grad():
                    out = model(tensor_cache[key])[0].tolist()
                probs: dict[str, float] = {}
                for j, code in codes.items():
                    probs[code] = max(probs.get(code, 0.0), float(out[j]))
                recs.append({"kind": kind, "y": y, "probs": probs,
                             "raw_pneumonia": float(out[raw_idx]) if raw_idx is not None else None})
                if i % 500 == 0:
                    print(f"{weights} [{tag}]: {i}/{len(imgs)}", flush=True)
            return recs

        records = infer(images, "оценка")
        summary = summarize(records, thresholds, bootstrap=a.bootstrap)
        summary["weights_hash"] = weights_hash
        if calib_images:
            calib = infer(calib_images, "подбор")
            summary["normal_floor_calibration"] = {
                "calibration_split": a.calibrate_split,
                "calibration_normals": sum(1 for r in calib if r["y"] == 0),
                "by_rate": {},
            }
            for rate in a.normal_rate:
                th = normal_floor_thresholds(calib, thresholds, rate)
                s = summarize(records, th, bootstrap=0)
                summary["normal_floor_calibration"]["by_rate"][str(rate)] = {
                    "thresholds": th,
                    **{k: s[k] for k in ("normal_with_any_draft", "normal_mean_drafts", "pneumonia_with_any_draft",
                                         "with_any_draft_by_kind")},
                    "per_code_draft_rates": {
                        c: {"normal": v["draft_rate_normal"], "pneumonia": v["draft_rate_pneumonia"]}
                        for c, v in s["per_code"].items()},
                }
        if a.apply_calibration:
            src = json.loads(Path(a.apply_calibration).read_text("utf-8"))["models"].get(weights, {})
            ext = {}
            for rate, cal in (src.get("normal_floor_calibration") or {}).get("by_rate", {}).items():
                s = summarize(records, cal["thresholds"], bootstrap=0)
                ext[rate] = {k: s[k] for k in ("normal_with_any_draft", "normal_mean_drafts",
                                               "pneumonia_with_any_draft", "with_any_draft_by_kind")}
            summary["external_calibration_check"] = {"source": Path(a.apply_calibration).name, "by_rate": ext}
        summary["seconds"] = round(time.monotonic() - t0, 1)
        report["models"][weights] = summary
        print(json.dumps({weights: {k: summary[k] for k in ("n", "any_finding_auroc", "any_finding_auroc_ci95",
                                                            "normal_with_any_draft", "pneumonia_with_any_draft")}},
                         ensure_ascii=False), flush=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(f"Отчёт: {a.out}")


if __name__ == "__main__":
    main()
