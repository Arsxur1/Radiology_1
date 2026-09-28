"""Запуск TotalSegmentator в отдельном процессе.

nnU-Net создаёт пул процессов, а процессы воркера Celery (prefork) — «демонические» и
детей иметь не могут. Отдельный процесс снимает это ограничение и изолирует память
тяжёлой модели от воркера.

    python -m app.workers.totalseg_runner <каталог DICOM> <выход.nii.gz> [--full] [--device cpu]
"""

from __future__ import annotations

import argparse


def main() -> None:  # pragma: no cover - нужен TotalSegmentator
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--full", action="store_true")
    p.add_argument("--device", default="cpu")
    p.add_argument("--task", default="total", choices=["total", "total_mr"])
    a = p.parse_args()

    from totalsegmentator.python_api import totalsegmentator

    totalsegmentator(a.input, a.output, ml=True, fast=not a.full, task=a.task, device=a.device, quiet=True)


if __name__ == "__main__":
    main()
