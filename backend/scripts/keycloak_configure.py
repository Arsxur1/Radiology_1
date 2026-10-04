"""Прописать адрес сервера клиники в клиенты входа Keycloak (после установки/смены IP).

    python scripts/keycloak_configure.py            # адрес берётся из KEYCLOAK_PUBLIC_URL
    python scripts/keycloak_configure.py --host 10.0.0.50

medviz-web  → http://<host>/*       (рабочее место врача через шлюз)
medviz-ohif → http://<host>:3000/*  (просмотрщик)
medviz-backend — только аудитория токенов: все способы получить токен выключены, секрет
перевыпускается (в старом realm был известный «change_me_keycloak»).
Плюс настройки безопасности входа (SECURITY) — применяются и к уже работающему realm:
импорт realm-medviz.json срабатывает только при первом запуске Keycloak.
Администратор Keycloak — из KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD. Идемпотентно.
"""

from __future__ import annotations

import argparse
import os
from urllib.parse import urlparse

import httpx

# Безопасность входа сотрудников. Совпадает с infra/keycloak/realm-medviz.json (тест следит).
SECURITY: dict = {
    # Подбор пароля: после 5 ошибок — пауза, растущая до 15 мин; сбрасывается через 12 ч.
    "bruteForceProtected": True,
    "permanentLockout": False,
    "failureFactor": 5,
    "waitIncrementSeconds": 60,
    "maxFailureWaitSeconds": 900,
    "maxDeltaTimeSeconds": 43200,
    "quickLoginCheckMilliSeconds": 1000,
    "minimumQuickLoginWaitSeconds": 60,
    # Пароли: от 12 символов, разные классы, без имени пользователя внутри, не почта,
    # не 3 последних. notUsername запрещает только точное совпадение — поэтому и
    # notContainsUsername (проверено: «Policy.test12345A» для policy.test иначе проходил).
    "passwordPolicy": "length(12) and upperCase(1) and lowerCase(1) and digits(1) and "
                      "notUsername(undefined) and notContainsUsername(undefined) and "
                      "notEmail(undefined) and passwordHistory(3)",
    # Сессия: 30 мин без действий, не дольше смены (10 ч).
    "ssoSessionIdleTimeout": 1800,
    "ssoSessionMaxLifespan": 36000,
    "accessTokenLifespan": 600,
    # Журнал входов и действий администратора (без содержимого запросов — там бывают пароли).
    "eventsEnabled": True,
    "eventsExpiration": 7776000,
    "adminEventsEnabled": True,
    "adminEventsDetailsEnabled": False,
    # Ни «запомнить меня», ни самостоятельной регистрации и сброса по почте: учётные записи
    # и пароли выдаёт администратор лично.
    "rememberMe": False,
    "registrationAllowed": False,
    "resetPasswordAllowed": False,
}


# Клиент backend — только аудитория (aud) токенов medviz-web/medviz-ohif. Сам он токены не
# выдаёт: иначе вход по паролю в обход страницы входа. Совпадает с realm-medviz.json (тест).
AUDIENCE_CLIENT = "medviz-backend"
AUDIENCE_ONLY: dict = {
    "standardFlowEnabled": False,
    "directAccessGrantsEnabled": False,
    "implicitFlowEnabled": False,
    "serviceAccountsEnabled": False,
}


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
    c = httpx.get(f"{base}/admin/realms/{realm}/clients", params={"clientId": AUDIENCE_CLIENT}, headers=h)
    client = c.raise_for_status().json()[0]
    httpx.put(f"{base}/admin/realms/{realm}/clients/{client['id']}", json={**client, **AUDIENCE_ONLY},
              headers=h).raise_for_status()
    # Новый случайный секрет вместо известного из старого realm (значение не печатаем).
    httpx.post(f"{base}/admin/realms/{realm}/clients/{client['id']}/client-secret", headers=h).raise_for_status()
    print(f"{AUDIENCE_CLIENT}: только аудитория токенов, выдача токенов выключена, секрет перевыпущен")
    r = httpx.get(f"{base}/admin/realms/{realm}", headers=h).raise_for_status().json()
    httpx.put(f"{base}/admin/realms/{realm}", json={**r, **SECURITY}, headers=h).raise_for_status()
    print("безопасность входа: защита от подбора, политика паролей, журнал входов — применены")


if __name__ == "__main__":
    main()
