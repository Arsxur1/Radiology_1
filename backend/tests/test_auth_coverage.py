"""Каждый эндпоинт, кроме проверок живости, требует аутентификации (FR-12).

Тест обходит OpenAPI-схему: новый маршрут без защиты сразу валит сборку.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app

PUBLIC = {("GET", "/"), ("GET", "/health"), ("GET", "/ready")}
DUMMY = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _operations():
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            yield method.upper(), path


def test_every_non_public_endpoint_requires_auth(client):
    open_ = []
    for method, path in _operations():
        code = client.request(method, re.sub(r"\{[^}]+\}", DUMMY, path), json={}).status_code
        if (method, path) not in PUBLIC and code not in (401, 403):
            open_.append((method, path, code))
    assert open_ == [], f"Эндпоинты без аутентификации: {open_}"


def test_public_endpoints_stay_public(client):
    for method, path in PUBLIC:
        assert client.request(method, path).status_code == 200


def _as(role):
    return {"X-Debug-Subject": "u", "X-Debug-Roles": role}


def test_patient_lookup_limited_to_clinical_roles(client):
    url = "/patients/search/by-identifier?value=x"
    assert client.get(url, headers=_as("researcher")).status_code == 403   # только обезличенные данные
    assert client.get(url, headers=_as("auditor")).status_code == 403
    assert client.get(url, headers=_as("radiologist")).status_code == 200


def test_reports_not_for_researcher(client):
    assert client.get(f"/reports/{DUMMY}", headers=_as("researcher")).status_code == 403
    assert client.get(f"/reports/{DUMMY}", headers=_as("clinician")).status_code == 404
