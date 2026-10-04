"""Настройки безопасности входа одинаковы в realm для первого запуска и в скрипте для
работающего Keycloak — иначе площадка, поднятая раньше, осталась бы без защиты."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("kc", ROOT / "backend/scripts/keycloak_configure.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _security() -> dict:
    return _module().SECURITY


def test_realm_json_matches_configure_script():
    realm = json.loads((ROOT / "infra/keycloak/realm-medviz.json").read_text(encoding="utf-8"))
    sec = _security()
    assert {k: realm.get(k) for k in sec} == sec


def test_security_baseline():
    sec = _security()
    assert sec["bruteForceProtected"] and sec["failureFactor"] <= 5
    assert "length(12)" in sec["passwordPolicy"] and "notContainsUsername" in sec["passwordPolicy"]
    assert sec["eventsEnabled"] and sec["adminEventsEnabled"] and not sec["adminEventsDetailsEnabled"]
    assert not sec["registrationAllowed"] and not sec["rememberMe"]
    assert sec["ssoSessionIdleTimeout"] <= 1800


def test_backend_client_is_audience_only_without_known_secret():
    """medviz-backend не выдаёт токены (ни по паролю, ни по коду), известного секрета нет;
    скрипт приводит к тому же работающий Keycloak и перевыпускает секрет."""
    mod = _module()
    realm = json.loads((ROOT / "infra/keycloak/realm-medviz.json").read_text(encoding="utf-8"))
    client = next(c for c in realm["clients"] if c["clientId"] == mod.AUDIENCE_CLIENT)
    assert {k: client.get(k) for k in mod.AUDIENCE_ONLY} == mod.AUDIENCE_ONLY
    assert not any(mod.AUDIENCE_ONLY.values())
    assert "secret" not in client
    text = (ROOT / "infra/keycloak/realm-medviz.json").read_text(encoding="utf-8")
    assert "change_me" not in text


def test_no_known_default_secrets_in_infra():
    """Учебные пароли не вшиты в конфигурацию: только из .env (в шаблоне .env — заглушки)."""
    for p in (ROOT / "infra").rglob("*"):
        if p.is_file() and p.suffix in {".json", ".sql", ".conf", ".template", ".sh", ".envsh", ".yml"}:
            assert "change_me" not in p.read_text(encoding="utf-8", errors="ignore"), p
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count("ORTHANC__REGISTERED_USERS") == 2 and "change_me" not in compose
