"""docker-compose.yml — разбирается и задаёт то, на что опираются меры безопасности.

Проверка строкой не ловит сломанный YAML (так и случилось 4 октября: блок окружения попал
внутрь списка томов, строка была на месте, compose не запускался).
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_orthanc_credentials_only_from_env():
    for name in ("orthanc-raw", "orthanc-clean"):
        svc = SERVICES[name]
        assert isinstance(svc["volumes"], list) and len(svc["volumes"]) == 2, name
        users = svc["environment"]["ORTHANC__REGISTERED_USERS"]
        assert "${ORTHANC_USERNAME}" in users and "${ORTHANC_PASSWORD}" in users, name


def test_every_service_rotates_logs():
    for name, svc in SERVICES.items():
        opts = svc["logging"]["options"]
        assert svc["logging"]["driver"] == "json-file" and opts["max-size"] and opts["max-file"], name


def test_internal_ports_bound_to_localhost():
    """Наружу — только приём DICOM (4242) и шлюз; остальное — только с самого сервера."""
    public = set()
    for name, svc in SERVICES.items():
        for p in svc.get("ports", []):
            if not str(p).startswith("127.0.0.1:"):
                public.add((name, str(p).split(":")[-1]))
    assert public == {("orthanc-raw", "4242"), ("web", "80"), ("web", "443"), ("web", "3000")}, public
