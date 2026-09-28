"""Клиент Orthanc (raw и clean узлы). DICOMweb/REST."""

from __future__ import annotations

import httpx

from app.core.config import get_settings


class OrthancClient:
    def __init__(self, base_url: str) -> None:
        s = get_settings()
        self._client = httpx.Client(
            base_url=base_url,
            auth=(s.orthanc_username, s.orthanc_password),
            timeout=30.0,
        )

    def get_changes(self, since: int = 0, limit: int = 100) -> dict:
        r = self._client.get("/changes", params={"since": since, "limit": limit})
        r.raise_for_status()
        return r.json()

    def get_instance_tags(self, instance_id: str) -> dict:
        r = self._client.get(f"/instances/{instance_id}/simplified-tags")
        r.raise_for_status()
        return r.json()

    def get_instance_file(self, instance_id: str) -> bytes:
        r = self._client.get(f"/instances/{instance_id}/file")
        r.raise_for_status()
        return r.content

    def upload_dicom(self, data: bytes) -> dict:
        r = self._client.post(
            "/instances", content=data, headers={"Content-Type": "application/dicom"}
        )
        r.raise_for_status()
        return r.json()

    def series_preview_png(self, series_instance_uid: str) -> bytes | None:
        """PNG-превью первого снимка серии (рендер Orthanc, с его оконными настройками)."""
        r = self._client.post("/tools/lookup", content=series_instance_uid)
        r.raise_for_status()
        match = next((m for m in r.json() if m.get("Type") == "Series"), None)
        if match is None:
            return None
        r = self._client.get(f"/series/{match['ID']}")
        r.raise_for_status()
        instances = sorted(r.json().get("Instances", []))
        if not instances:
            return None
        r = self._client.get(f"/instances/{instances[0]}/preview", headers={"Accept": "image/png"})
        r.raise_for_status()
        return r.content

    def close(self) -> None:
        self._client.close()


def raw_client() -> OrthancClient:
    return OrthancClient(get_settings().orthanc_raw_url)


def clean_client() -> OrthancClient:
    return OrthancClient(get_settings().orthanc_clean_url)
