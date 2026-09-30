"""Прописать адрес сервера клиники в клиенты входа Keycloak (после установки/смены IP).

    python scripts/keycloak_configure.py            # адрес берётся из KEYCLOAK_PUBLIC_URL
    python scripts/keycloak_configure.py --host 10.0.0.50

medviz-web  → http://<host>/*       (рабочее место врача через шлюз)
medviz-ohif → http://<host>:3000/*  (просмотрщик)
Администратор Keycloak — из KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD. Идемпотентно.
"""

from __future__ import annotations

import argparse
import os
from urllib.parse import urlparse

import httpx


def targets(host: str) -> dict[str, list[str]]:
    return {
        "medviz-web": [f"http://{host}/*", f"https://{host}/*"],
        "medviz-ohif": [f"http://{host}:3000/*", f"https://{host}:3000/*"],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", help="IP или имя сервера платформы в сети клиники")
    a = p.parse_args()
    host = a.host or urlparse(os.environ.get("KEYCLOAK_PUBLIC_URL", "")).hostname
    if not host:
        raise SystemExit("Укажите --host или KEYCLOAK_PUBLIC_URL")
    base = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080").rstrip("/")
    realm = os.environ.get("KEYCLOAK_REALM", "medviz")
    tok = httpx.post(f"{base}/realms/master/protocol/openid-connect/token", data={
        "client_id": "admin-cli", "grant_type": "password",
        "username": os.environ["KEYCLOAK_ADMIN"], "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"],
    }).raise_for_status().json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    for client_id, uris in targets(host).items():
        c = httpx.get(f"{base}/admin/realms/{realm}/clients", params={"clientId": client_id}, headers=h)
        client = c.raise_for_status().json()[0]
        client["redirectUris"] = sorted(set(client.get("redirectUris", [])) | set(uris))
        client["webOrigins"] = ["+"]
        httpx.put(f"{base}/admin/realms/{realm}/clients/{client['id']}", json=client, headers=h).raise_for_status()
        print(f"{client_id}: {', '.join(client['redirectUris'])}")


if __name__ == "__main__":
    main()
