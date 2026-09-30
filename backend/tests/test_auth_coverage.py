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

PUBLIC = {("GET", "/"), ("GET", "/health"), ("GET", "/ready"), ("GET", "/auth/config")}
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


def test_auth_check_for_gateway(client):
    assert client.get("/auth/check").status_code == 401
    assert client.get("/auth/check", headers=_as("researcher")).status_code == 204


def test_issuer_public_and_jwks_internal(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("KEYCLOAK_URL", "http://keycloak:8080")
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "http://10.0.0.50:8080")
    s = Settings(_env_file=None)
    assert s.oidc_issuer == "http://10.0.0.50:8080/realms/medviz"
    assert s.oidc_jwks_url == "http://keycloak:8080/realms/medviz/protocol/openid-connect/certs"


def test_data_access_is_audited(client, db):
    from datetime import datetime

    from app.models.audit import AuditAction, AuditLog
    from app.models.imaging import Study
    from app.models.patient import Patient

    p = Patient()
    db.add(p)
    db.flush()
    st = Study(patient_id=p.id, study_instance_uid="1.2.3", modality="DX", study_date=datetime(2026, 9, 1))
    db.add(st)
    db.commit()
    client.get(f"/studies/{st.id}", headers=_as("clinician"))
    client.get(f"/patients/{p.id}", headers=_as("radiologist"))
    client.get("/patients/search/by-identifier?value=Karimov", headers=_as("radiologist"))
    client.post("/learning/site-manifest", headers=_as("researcher"))
    rows = db.query(AuditLog).order_by(AuditLog.created_at).all()
    got = [(r.actor_role, r.action, r.entity_type) for r in rows]
    assert ("clinician", AuditAction.PATIENT_ACCESS, "study") in got
    assert ("radiologist", AuditAction.PATIENT_ACCESS, "patient") in got
    assert ("researcher", AuditAction.EXPORT, "site_manifest") in got
    search = next(r for r in rows if r.entity_type == "patient_search")
    assert "Karimov" not in str(search.details)                 # сам идентификатор в журнал не попадает


def test_audit_chain_order_by_sequence(db):
    from app.models.audit import AuditAction, AuditLog
    from app.services import audit

    for i in range(20):                       # одна транзакция — одинаковое время начала
        audit.record(db, actor=f"a{i}", action=AuditAction.PATIENT_ACCESS, entity_type="t")
    db.commit()
    seqs = [r.seq for r in db.query(AuditLog).order_by(AuditLog.seq)]
    assert seqs == list(range(1, 21)) and audit.verify_chain(db)
