"""Бакеты хранилища на новой установке (найдено на стенде 4 октября: первый приём падал)."""

from __future__ import annotations

import pytest
from minio.error import S3Error

from app.services import storage


class FakeMinio:
    def __init__(self, buckets=()):
        self.buckets = set(buckets)
        self.objects = {}

    def bucket_exists(self, b):
        return b in self.buckets

    def make_bucket(self, b):
        self.buckets.add(b)

    def put_object(self, bucket, key, data, length, content_type):
        if bucket not in self.buckets:
            raise S3Error(None, "NoSuchBucket", "The specified bucket does not exist", f"/{bucket}", "r", None)
        self.objects[(bucket, key)] = data.read()


def test_put_object_creates_missing_buckets_and_retries(monkeypatch):
    fake = FakeMinio()
    monkeypatch.setattr(storage, "get_minio", lambda: fake)
    assert storage.put_object("images", "a/b.dcm", b"DICM") == "images/a/b.dcm"
    assert fake.objects[("images", "a/b.dcm")] == b"DICM"
    assert {"images", "masks", "meshes"} <= fake.buckets


def test_other_s3_errors_are_not_hidden(monkeypatch):
    class Denied(FakeMinio):
        def put_object(self, *a, **k):
            raise S3Error(None, "AccessDenied", "denied", "/images", "r", None)

    monkeypatch.setattr(storage, "get_minio", lambda: Denied({"images"}))
    with pytest.raises(S3Error):
        storage.put_object("images", "k", b"x")


def test_ensure_buckets_safely_never_raises(monkeypatch):
    def boom():
        raise ConnectionError("хранилище недоступно")

    monkeypatch.setattr(storage, "get_minio", boom)
    assert storage.ensure_buckets_safely() is False
    fake = FakeMinio()
    monkeypatch.setattr(storage, "get_minio", lambda: fake)
    assert storage.ensure_buckets_safely() is True and {"images", "masks", "meshes"} <= fake.buckets


def test_api_and_worker_create_buckets_on_start():
    import inspect

    from app import main
    from app.workers import celery_app

    assert "ensure_buckets_safely" in inspect.getsource(main._lifespan)
    assert "ensure_buckets_safely" in inspect.getsource(celery_app._ensure_buckets)
