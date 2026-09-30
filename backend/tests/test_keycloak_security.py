"""Настройки безопасности входа одинаковы в realm для первого запуска и в скрипте для
работающего Keycloak — иначе площадка, поднятая раньше, осталась бы без защиты."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _security() -> dict:
    spec = importlib.util.spec_from_file_location("kc", ROOT / "backend/scripts/keycloak_configure.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SECURITY


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
