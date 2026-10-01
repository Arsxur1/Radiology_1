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
        if (method, path) in PUBLIC:
            continue                     # публичные проверяет test_public_endpoints_stay_public
        code = client.request(method, re.sub(r"\{[^}]+\}", DUMMY, path), json={}).status_code
        if code not in (401, 403):
            open_.append((method, path, code))
    assert open_ == [], f"Эндпоинты без аутентификации: {open_}"


def test_public_endpoints_stay_public(client, monkeypatch):
    from app.services import system_status as ss

    # /ready — настоящие проверки (без сервисов в тестах был бы 503): подменяем их быстрыми.
    monkeypatch.setattr(ss, "collect", lambda: ss.summarize([]))
    for method, path in PUBLIC:
        assert client.request(method, path).status_code == 200, path


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


def test_audit_api_filters_paging_export(client, db):
    from app.models.audit import AuditAction
    from app.services import audit

    for i in range(5):
        audit.record(db, actor=f"dr.{i % 2}", action=AuditAction.PATIENT_ACCESS, entity_type="study")
    audit.record(db, actor="admin", action=AuditAction.MODE_CHANGE, entity_type="mode")
    db.commit()
    h = _as("auditor")
    assert client.get("/audit", headers=_as("radiologist")).status_code == 403
    rows = client.get("/audit?actor=dr.1", headers=h).json()
    assert len(rows) == 2 and all(r["actor"] == "dr.1" for r in rows)
    page1 = client.get("/audit?limit=3", headers=h).json()
    page2 = client.get(f"/audit?limit=3&before_seq={page1[-1]['seq']}", headers=h).json()
    assert [r["seq"] for r in page1 + page2] == [6, 5, 4, 3, 2, 1]
    assert len(client.get("/audit?action=mode_change", headers=h).json()) == 1
    csv_resp = client.get("/audit/export.csv?entity_type=study", headers=h)
    assert csv_resp.status_code == 200 and csv_resp.text.count("\n") == 6       # заголовок + 5
    last = client.get("/audit?limit=1", headers=h).json()[0]
    assert last["action"] == "export" and last["entity_type"] == "audit_log"     # выгрузка журналирована


def test_identity_reveal_is_role_limited_and_audited(client, db):
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.session import get_idmap_db
    from app.models.audit import AuditLog
    from app.models.idmap import IdMapBase, PatientPseudonymMap
    from app.models.imaging import Study
    from app.models.patient import Patient

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    IdMapBase.metadata.create_all(eng)
    idmap = sessionmaker(bind=eng)()
    app.dependency_overrides[get_idmap_db] = lambda: idmap
    p = Patient()
    db.add(p)
    db.flush()
    st = Study(patient_id=p.id, study_instance_uid="2.25.1", modality="DX", study_date=datetime(2026, 9, 1))
    db.add(st)
    db.commit()
    idmap.add(PatientPseudonymMap(pseudonym_patient_id=p.id, real_mrn="NCMC-777", real_name="Karimov^Aziz",
                                  real_study_instance_uid="1.2.840.99", pseudonym_study_instance_uid="2.25.1"))
    idmap.commit()

    url = f"/studies/{st.id}/identity"
    assert client.get(f"{url}?purpose=report", headers=_as("researcher")).status_code == 403
    assert client.get(f"{url}?purpose=report", headers=_as("auditor")).status_code == 403
    assert client.get(f"{url}?purpose=curiosity", headers=_as("radiologist")).status_code == 422
    r = client.get(f"{url}?purpose=report", headers=_as("radiologist"))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["patient_name"] == "Karimov Aziz" and r.json()["patient_mrn"] == "NCMC-777"
    log = db.query(AuditLog).filter(AuditLog.entity_type == "identity").all()
    assert len(log) == 1 and log[0].details["purpose"] == "report"
    assert "Karimov" not in str(log[0].details)            # в журнале — факт и цель, не сами PHI


def test_audit_verify_reports_where_chain_breaks(db):
    from app.models.audit import AuditAction, AuditLog
    from app.services import audit

    for i in range(5):
        audit.record(db, actor=f"dr.{i}", action=AuditAction.PATIENT_ACCESS, entity_type="study")
    db.commit()
    assert audit.verify_chain_report(db, batch=2) == {"intact": True, "checked": 5, "broken_at_seq": None}
    row = db.query(AuditLog).filter(AuditLog.seq == 3).one()
    row.actor = "подмена"                          # тестовая БД без триггера: имитация подделки
    db.commit()
    assert audit.verify_chain_report(db, batch=2) == {"intact": False, "checked": 2, "broken_at_seq": 3}
    assert audit.verify_chain(db) is False


def test_audit_csv_neutralizes_formulas(client, db):
    from app.api.routes_audit import csv_safe
    from app.models.audit import AuditAction
    from app.services import audit

    assert csv_safe('=HYPERLINK("http://x","y")').startswith("'=")
    assert csv_safe("+7 999") == "'+7 999" and csv_safe("dr.ivanov") == "dr.ivanov" and csv_safe(None) == ""
    audit.record(db, actor="=cmd|' /C calc'!A0", action=AuditAction.PATIENT_ACCESS, entity_type="study")
    db.commit()
    body = client.get("/audit/export.csv", headers=_as("auditor")).text
    assert "'=cmd" in body and ",=cmd" not in body
