"""Проверка рентген-модели на детских НАХОДКАХ: VinDr-PCXR (PhysioNet, только исследования).

Запускать ТОЛЬКО на своём компьютере или сервере NCMC, где лежит набор. Соглашение PhysioNet
запрещает загружать снимки, CSV и отчёты набора в онлайн-ИИ-сервисы (включая чат с ИИ).
Разработчику передаётся только итоговый файл --out: в нём лишь сводные цифры.

    python scripts/eval_vindr_pcxr.py --root /data/vindr-pcxr/1.0.0 --out vindr-pcxr.json
    python scripts/eval_vindr_pcxr.py --root ... --weights densenet121-res224-nih densenet121-res224-all --out ...
    python scripts/eval_vindr_pcxr.py --root ... --limit 50 --out probe.json     # сначала — пробный прогон

--root — папка релиза: train/, test/ (файлы <image_id>.dicom) и image_labels_*.csv,
annotations_*.csv (в корне или в annotations/). По умолчанию — тестовая часть (размечена
несколькими врачами, используется большинство). Модель, предобработка, коды находок и пороги —
те же, что у кандидата в платформе. Отчёт загружается в админке как внешняя детская проверка
кандидата (по хешу весов).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CITATION = ("Pham H.H. et al. PediCXR: An open, large-scale chest radiograph dataset for interpretation of "
            "common thoracic diseases in children. PhysioNet, VinDr-PCXR v1.0.0, doi:10.13026/k8qc-na36")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", required=True, help="папка релиза VinDr-PCXR")
    p.add_argument("--weights", nargs="+", default=["densenet121-res224-nih"])
    p.add_argument("--splits", nargs="+", default=["test"], help="test (по умолчанию), train, validate")
    p.add_argument("--reader-policy", default="majority", choices=["majority", "any"],
                   help="как сводить метки нескольких врачей")
    p.add_argument("--limit", type=int, default=0, help="не больше N снимков (пробный прогон)")
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    import torch
    import torchxrayvision as xrv

    from app.services.classification import xrv_code_map, xrv_tensor
    from app.training.model_card import weights_sha256
    from app.training.sources import parse_vindr
    from app.training.vindr_eval import collect_records, summarize_findings
    from app.training.xrv import xrv_thresholds

    manifest, mapping = parse_vindr(Path(a.root), "vindr-pcxr", reader_policy=a.reader_policy)
    if not any(m.split in a.splits for m in manifest):
        raise SystemExit(f"В {a.root} нет снимков частей {a.splits}")
    torch.set_num_threads(4)
    report = {
        "kind": "external_pediatric",
        "dataset": "VinDr-PCXR (" + ", ".join(a.splits) + ")",
        "citation": CITATION,
        "source": "PhysioNet VinDr-PCXR 1.0.0 — Restricted Health Data License 1.5.0: только научные "
                  "исследования; отчёт содержит только сводные цифры",
        "research_only": True,
        "splits": a.splits,
        "reader_policy": a.reader_policy,
        # Какие метки набора сведены к кодам находок, а какие — нет (диагнозы, размытые, без пары).
        "label_mapping": {"mapped": len(mapping.mapped), "excluded_diagnoses": mapping.excluded_diagnoses,
                          "excluded_vague": mapping.excluded_vague, "unmapped": mapping.unmapped},
        "models": {},
    }
    for weights in a.weights:
        info = xrv.models.model_urls[weights]
        model = xrv.models.DenseNet(weights=weights).eval()
        wfile = Path(xrv.utils.get_cache_dir()) / info["weights_url"].split("/")[-1]
        pathologies = list(model.pathologies)
        codes = xrv_code_map(pathologies)
        thresholds = xrv_thresholds(pathologies, [float(x) for x in info["ppv80_thres"]]
                                    if "ppv80_thres" in info else None)

        def score(arr, model=model, codes=codes):
            with torch.no_grad():
                out = model(xrv_tensor(arr))[0].tolist()
            probs: dict[str, float] = {}
            for j, code in codes.items():
                probs[code] = max(probs.get(code, 0.0), float(out[j]))
            return probs

        t0 = time.monotonic()
        records = collect_records(a.root, manifest, score, splits=tuple(a.splits), limit=a.limit,
                                  progress=lambda i, n, w=weights: print(f"{w}: {i}/{n}", flush=True))
        summary = summarize_findings(records, thresholds, bootstrap=a.bootstrap)
        summary["weights_hash"] = weights_sha256(wfile) if wfile.exists() else None
        summary["seconds"] = round(time.monotonic() - t0, 1)
        report["models"][weights] = summary
        print(json.dumps({weights: {k: summary[k] for k in ("n", "any_finding_auroc", "normal_with_any_draft",
                                                            "abnormal_with_any_draft")}}, ensure_ascii=False),
              flush=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(f"Отчёт (только сводные цифры): {a.out}")


if __name__ == "__main__":
    main()
