"""CLI офлайн-контура обучения (ТЗ, FR-10).

Порядок работы на обучающем сервере (MEDVIZ_CONTOUR=training):
  1. manifest  — разобрать каждый датасет в единый манифест + отчёт по меткам;
  2. freeze    — сформировать замороженный тест ДО обучения (FR-10 п. 4);
  3. train     — дообучить кандидата (отдельно для взрослых и детей);
  4. evaluate  — оценить на замороженном тесте (для гейта продвижения);
  import-site  — метки врачей площадки (POST /learning/site-manifest) → манифест «ncmc»;
  5. зарегистрировать кандидата: POST /models/candidates с registration.json → SHADOW.

Команда `labels` не трогает данные и доступна везде — для проверки маппинга меток.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.training.contour import ContourError, require_training_contour
from app.training.label_map import map_labels
from app.training.manifest import ManifestRecord, label_stats, read_jsonl, write_jsonl
from app.training.sources import DATASETS, SourceError, parse_dataset
from app.training.splits import FrozenTestError, freeze_test_set, load_frozen, training_records

SITE_DATASET = "ncmc"


def import_site(data: dict) -> tuple[list[ManifestRecord], dict]:
    """Проверить экспорт площадки: только коды словаря, известные популяции и сплиты."""
    from app.services.finding_vocabulary import by_code

    records, rejected = [], {"unknown_codes": set(), "bad_records": 0}
    for raw in data.get("records", []):
        try:
            r = ManifestRecord(**raw)
        except TypeError:
            rejected["bad_records"] += 1
            continue
        if r.dataset != SITE_DATASET or r.population not in ("adult", "pediatric") \
                or r.split not in ("train", "validate", "test"):
            rejected["bad_records"] += 1
            continue
        unknown = {c for c in r.labels if by_code(c) is None}
        rejected["unknown_codes"] |= unknown
        r.labels = {c: v for c, v in r.labels.items() if c not in unknown and v in (0, 1, None)}
        records.append(r)
    rejected["unknown_codes"] = sorted(rejected["unknown_codes"])
    return records, rejected


def cmd_import_site(args) -> dict:
    data = json.loads(Path(args.json).read_text("utf-8"))
    records, rejected = import_site(data)
    out = Path(args.out)
    write_jsonl(records, out)
    report = {"records": len(records), **rejected, "site_report": data.get("report", {}),
              "label_stats": label_stats(records)}
    out.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return {k: report[k] for k in ("records", "bad_records", "unknown_codes")}


def _roots(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs or []:
        key, _, path = pair.partition("=")
        if key not in (*DATASETS, SITE_DATASET) or not path:
            raise SystemExit(f"--root ожидает <датасет>=<путь>, получено {pair!r}")
        out[key] = path
    return out


def _load(manifests: list[str], population: str | None = None):
    records = [r for m in manifests for r in read_jsonl(Path(m))]
    return [r for r in records if population is None or r.population == population]


def cmd_labels(args) -> dict:
    report = map_labels([s.strip() for s in args.labels.split(",") if s.strip()])
    return {
        "mapped": report.mapped,
        "excluded_diagnoses": report.excluded_diagnoses,
        "excluded_vague": report.excluded_vague,
        "unmapped": report.unmapped,
    }


def cmd_manifest(args) -> dict:
    records, report = parse_dataset(args.dataset, Path(args.root))
    out = Path(args.out)
    write_jsonl(records, out)
    summary = {
        "dataset": args.dataset,
        "records": len(records),
        "splits": {s: sum(1 for r in records if r.split == s) for s in ("train", "validate", "test")},
        "mapped": report.mapped,
        "excluded_diagnoses": report.excluded_diagnoses,
        "excluded_vague": report.excluded_vague,
        "unmapped": report.unmapped,
        "label_stats": label_stats(records),
    }
    out.with_suffix(".report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    return summary


def cmd_freeze(args) -> dict:
    frozen = freeze_test_set(_load(args.manifest, args.population), Path(args.out), force=args.force)
    return {"frozen": args.out, "images": len(frozen.image_ids), "digest": frozen.digest}


def cmd_train(args) -> dict:  # pragma: no cover - нужен torch
    from app.training.train import train

    frozen = load_frozen(Path(args.frozen))
    records, leaked = training_records(_load(args.manifest, args.population), frozen)
    excluded: list[str] = []
    for m in args.manifest:
        rep = Path(m).with_suffix(".report.json")
        if rep.exists():
            data = json.loads(rep.read_text("utf-8"))
            excluded += data.get("excluded_diagnoses", []) + data.get("excluded_vague", [])
    card = train(
        records=records, frozen=frozen, roots=_roots(args.root), population=args.population,
        out_dir=Path(args.out), name=args.name, semver=args.semver,
        excluded_labels=sorted(set(excluded)), epochs=args.epochs, batch_size=args.batch_size,
        lr=args.lr, image_size=args.image_size, num_workers=args.workers,
        age_min=args.age_min, age_max=args.age_max, pretrained=args.pretrained,
    )
    return {"run": args.out, "excluded_leaking_patients": leaked, "card": card}


def cmd_evaluate(args) -> dict:  # pragma: no cover - нужен torch
    from app.training.train import evaluate_frozen

    return evaluate_frozen(
        run_dir=Path(args.run), records=_load(args.manifest), frozen=load_frozen(Path(args.frozen)),
        roots=_roots(args.root), image_size=args.image_size,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="medviz-train", description="Офлайн-контур дообучения (FR-10)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("labels", help="проверить сопоставление меток (без данных)")
    s.add_argument("--labels", required=True, help="метки через запятую")
    s.set_defaults(func=cmd_labels, needs_contour=False)

    s = sub.add_parser("manifest", help="датасет → манифест + отчёт по меткам")
    s.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    s.add_argument("--root", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_manifest, needs_contour=True)

    s = sub.add_parser("freeze", help="сформировать замороженный тест")
    s.add_argument("--manifest", nargs="+", required=True)
    s.add_argument("--population", choices=["adult", "pediatric"])
    s.add_argument("--out", required=True)
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_freeze, needs_contour=True)

    s = sub.add_parser("import-site", help="экспорт меток площадки → манифест ncmc")
    s.add_argument("--json", required=True, help="ответ POST /learning/site-manifest")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_import_site, needs_contour=True)

    for name, func in (("train", cmd_train), ("evaluate", cmd_evaluate)):
        s = sub.add_parser(name)
        s.add_argument("--manifest", nargs="+", required=True)
        s.add_argument("--frozen", required=True)
        s.add_argument("--root", action="append", required=True, help="<датасет>=<путь>")
        s.add_argument("--image-size", type=int, default=512)
        if name == "train":
            s.add_argument("--population", required=True, choices=["adult", "pediatric"])
            s.add_argument("--out", required=True)
            s.add_argument("--name", required=True)
            s.add_argument("--semver", default="0.1.0")
            s.add_argument("--epochs", type=int, default=5)
            s.add_argument("--batch-size", type=int, default=16)
            s.add_argument("--lr", type=float, default=1e-4)
            s.add_argument("--workers", type=int, default=4)
            s.add_argument("--age-min", type=float)
            s.add_argument("--age-max", type=float)
            s.add_argument("--pretrained", default="imagenet",
                           help="imagenet | путь к densenet121-*.pth (офлайн) | none (только проверка)")
        else:
            s.add_argument("--run", required=True)
        s.set_defaults(func=func, needs_contour=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.needs_contour:
            require_training_contour()
        result = args.func(args)
    except (ContourError, SourceError, FrozenTestError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
