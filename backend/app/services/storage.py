"""Объектное хранилище MinIO (ТЗ, раздел 4.2). Пиксели — только здесь, не в БД."""

from __future__ import annotations

from functools import lru_cache

from minio import Minio

from app.core.config import get_settings


@lru_cache
def get_minio() -> Minio:
    s = get_settings()
    return Minio(
        s.minio_endpoint,
        access_key=s.minio_access_key,
        secret_key=s.minio_secret_key,
        secure=s.minio_secure,
    )


def ensure_buckets() -> None:
    """Создать бакеты изображений/масок/мешей, если их нет."""
    s = get_settings()
    client = get_minio()
    for bucket in (s.bucket_images, s.bucket_masks, s.bucket_meshes):
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)


def put_object(bucket: str, key: str, data: bytes, content_type: str = "application/dicom") -> str:
    import io

    client = get_minio()
    client.put_object(bucket, key, io.BytesIO(data), length=len(data), content_type=content_type)
    return f"{bucket}/{key}"


def first_series_object(series_object_prefix: str) -> bytes:
    """Первый по имени DICOM-объект серии (для рентгена серия — обычно один снимок)."""
    s = get_settings()
    client = get_minio()
    keys = sorted(
        o.object_name
        for o in client.list_objects(s.bucket_images, prefix=f"{series_object_prefix}/", recursive=True)
        if o.object_name.endswith(".dcm")
    )
    if not keys:
        raise FileNotFoundError(f"Нет объектов серии {series_object_prefix}")
    resp = client.get_object(s.bucket_images, keys[0])
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def get_object_ref(ref: str) -> bytes:
    """Прочитать объект по ссылке вида «бакет/ключ» (как возвращает put_object)."""
    bucket, _, key = ref.partition("/")
    resp = get_minio().get_object(bucket, key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()
