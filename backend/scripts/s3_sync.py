"""Резервная копия и восстановление объектного хранилища; пересборка просмотрщика.

    python scripts/s3_sync.py dump <каталог>            — все бакеты → файлы
    python scripts/s3_sync.py restore <каталог>         — файлы → бакеты
    python scripts/s3_sync.py rebuild-viewer            — обезличенный Orthanc из S3
                                                          (снимки + контуры DICOM SEG)

Работает с любым S3-совместимым хранилищем (MinIO, SeaweedFS…) — без утилиты mc.
S3 — источник истины для пикселей: обезличенный Orthanc можно пересобрать из него.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _buckets():
    from app.core.config import get_settings

    s = get_settings()
    return [s.bucket_images, s.bucket_masks, s.bucket_meshes]


def dump(dest: Path) -> dict:
    from app.services.storage import get_minio

    client = get_minio()
    counts = {}
    for bucket in _buckets():
        n = 0
        if client.bucket_exists(bucket):
            for obj in client.list_objects(bucket, recursive=True):
                target = dest / bucket / obj.object_name
                target.parent.mkdir(parents=True, exist_ok=True)
                client.fget_object(bucket, obj.object_name, str(target))
                n += 1
        counts[bucket] = n
    return counts


def restore(src: Path) -> dict:
    from app.services.storage import ensure_buckets, get_minio

    ensure_buckets()
    client = get_minio()
    counts = {}
    for bucket in _buckets():
        root = src / bucket
        files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
        for f in files:
            client.fput_object(bucket, f.relative_to(root).as_posix(), str(f))
        counts[bucket] = len(files)
    return counts


def rebuild_viewer() -> dict:
    from app.core.config import get_settings
    from app.services.orthanc import clean_client
    from app.services.storage import get_minio

    s = get_settings()
    client, orthanc = get_minio(), clean_client()
    counts = {"images": 0, "seg": 0, "registered": 0}
    try:
        for bucket, prefix, kind in ((s.bucket_images, "", "images"), (s.bucket_masks, "seg/", "seg"),
                                     (s.bucket_masks, "registered/", "registered")):
            for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
                if not obj.object_name.endswith(".dcm"):
                    continue
                resp = client.get_object(bucket, obj.object_name)
                try:
                    orthanc.upload_dicom(resp.read())
                finally:
                    resp.close()
                    resp.release_conn()
                counts[kind] += 1
    finally:
        orthanc.close()
    return counts


def main(argv: list[str]) -> None:
    import json

    cmd = argv[0]
    if cmd == "dump":
        out = dump(Path(argv[1]))
    elif cmd == "restore":
        out = restore(Path(argv[1]))
    elif cmd == "rebuild-viewer":
        out = rebuild_viewer()
    else:
        raise SystemExit(__doc__)
    print(json.dumps({cmd: out}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
