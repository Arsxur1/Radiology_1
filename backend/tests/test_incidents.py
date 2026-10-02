"""Журнал инцидентов (ТЗ, раздел 9 п. 7): сообщение → разбор → закрытие с выводом."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditAction, AuditLog
from app.models.ml import Finding
from app.services import classification, incidents, system_status
from app.services.pilot_dashboard import build_dashboard

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_classification import FixedModel, _model, _series  # noqa: E402


@pytest.fixture
def finding(db):
    series = _series(db)
    model = _model(db)
    out = classification.classify_series(db, series=series, model_version=model,
                                         model=FixedModel({"CXR-200": 0.9}))
    db.commit()
    return db.get(Finding, out.finding_ids[0])


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str, roles: str) -> dict:
    return {"X-Debug-Subject": who, "X-Debug-Roles": roles}


def _report(client, finding, who="dr.a", roles="radiologist", severity="serious"):
    return client.post("/incidents", json={
        "kind": "ai_misleading", "severity": severity, "finding_id": str(finding.id),
        "description": "Черновик «образование» у здорового ребёнка, едва не ушёл в заключение",
    }, headers=_as(who, roles))


def test_report_links_study_and_model_from_finding(client, finding, db):
    r = _report(client, finding)
    assert r.status_code == 201, r.text
    body = r.json()
    from app.models.imaging import Series
    assert body["study_id"] == str(db.get(Series, finding.series_id).study_id)
    assert body["model_version_id"] == str(finding.inference_result.model_version_id)
    assert body["status"] == "new" and body["kind_label"].startswith("Находка ИИ")

    # В аудит — факт и вид, но не текст описания (там может оказаться лишнее).
    a = db.query(AuditLog).filter(AuditLog.action == AuditAction.INCIDENT).one()
    assert a.details["kind"] == "ai_misleading" and a.details["severity"] == "serious"
    assert "образование" not in str(a.details)


def test_validation_and_roles(client, finding):
    bad = client.post("/incidents", json={"kind": "other", "severity": "moderate", "description": "коротко"},
                      headers=_as("dr.a", "radiologist"))
    assert bad.status_code == 422
    unknown = client.post("/incidents", json={"kind": "nonsense", "severity": "moderate",
                                              "description": "достаточно длинное описание"},
                          headers=_as("dr.a", "radiologist"))
    assert unknown.status_code == 422
    # Исследователь и аудитор не сообщают; закрывает только администратор.
    assert _report(client, finding, who="r", roles="researcher").status_code == 403
    assert _report(client, finding, who="au", roles="auditor").status_code == 403
    inc = _report(client, finding).json()
    r = client.patch(f"/incidents/{inc['id']}", json={"status": "closed", "resolution": "разобрано полностью"},
                     headers=_as("dr.a", "radiologist"))
    assert r.status_code == 403


def test_visibility_own_vs_all(client, finding):
    _report(client, finding, who="dr.a")
    _report(client, finding, who="cl.b", roles="clinician", severity="near_miss")
    mine = client.get("/incidents", headers=_as("dr.a", "radiologist")).json()
    assert [i["reported_by"] for i in mine] == ["dr.a"]
    assert len(client.get("/incidents", headers=_as("au", "auditor")).json()) == 2
    assert len(client.get("/incidents", headers=_as("adm", "admin")).json()) == 2


def test_lifecycle_close_requires_resolution_and_reopen(client, finding, db):
    inc = _report(client, finding).json()
    url = f"/incidents/{inc['id']}"
    adm = _as("adm", "admin")
    assert client.patch(url, json={"status": "closed"}, headers=adm).status_code == 409   # без вывода нельзя
    r = client.patch(url, json={"status": "investigating"}, headers=adm)
    assert r.status_code == 200 and r.json()["status"] == "investigating"
    assert client.patch(url, json={"status": "new"}, headers=adm).status_code == 409      # назад нельзя
    r = client.patch(url, json={"status": "closed", "resolution": "Порог кода mass поднят калибровкой"},
                     headers=adm)
    assert r.status_code == 200 and r.json()["closed_by"] == "adm" and r.json()["closed_at"]
    r = client.patch(url, json={"status": "investigating"}, headers=adm)                  # повторное открытие
    assert r.json()["status"] == "investigating" and r.json()["closed_at"] is None
    events = [a.details for a in db.query(AuditLog).filter(AuditLog.action == AuditAction.INCIDENT)
              .order_by(AuditLog.seq)]
    assert [e["event"] for e in events] == ["reported", "status", "status", "status"]
    assert client.patch("/incidents/00000000-0000-0000-0000-000000000000", json={"status": "investigating"},
                        headers=adm).status_code == 404


def test_summary_dashboard_and_system_status(client, finding, db):
    _report(client, finding)                                            # серьёзный, открыт
    _report(client, finding, severity="near_miss")
    sm = incidents.summary(db)
    assert sm == {"total": 2, "open": 2, "open_serious": 1,
                  "by_kind": {"Находка ИИ могла повлиять на решение": 2}, "by_status": {"new": 2}}
    assert build_dashboard(db)["incidents"]["open_serious"] == 1
    assert client.get("/incidents/summary", headers=_as("au", "auditor")).json()["open"] == 2

    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    ok, detail, warn = system_status.check_incidents(lambda: _Ctx())
    assert ok and warn and "серьёзных 1" in detail
    checks = [system_status.Check("orthanc_clean", True, ""), system_status.Check("incidents", True, "", warn=True)]
    assert system_status.summarize(checks)["status"] == "degraded"
