"""SR-6: отклонение находки ИИ одним действием; причина — из закрытого списка, позже."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditAction, AuditLog
from app.models.ml import ConfirmationStatus, Finding
from app.services import classification, corrections
from app.services.corrections import REJECT_REASONS, CorrectionError
from app.services.pilot_dashboard import build_dashboard

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_classification import FixedModel, _model, _series  # noqa: E402


@pytest.fixture
def findings(db):
    out = classification.classify_series(db, series=_series(db), model_version=_model(db),
                                         model=FixedModel({"CXR-000": 0.1, "CXR-200": 0.9, "CXR-500": 0.9}))
    db.commit()
    return [db.get(Finding, i) for i in out.finding_ids]


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict:
    return {"X-Debug-Subject": who, "X-Debug-Roles": "radiologist"}


def test_one_action_reject_then_optional_reason(client, findings, db):
    f = findings[0]
    r = client.post(f"/findings/{f.id}/reject", json={"time_spent_seconds": 3}, headers=_as("dr.a"))
    assert r.status_code == 200                                     # одно действие — и всё
    assert r.json()["confirmation_status"] == "rejected" and r.json()["reject_reason"] is None

    r = client.post(f"/findings/{f.id}/reject-reason", json={"reason": "artifact"}, headers=_as("dr.a"))
    assert r.status_code == 200 and r.json()["reject_reason"] == "artifact"
    # Передумал — можно уточнить ещё раз; последнее слово остаётся.
    r = client.post(f"/findings/{f.id}/reject-reason", json={"reason": "false_positive"}, headers=_as("dr.a"))
    assert r.json()["reject_reason"] == "false_positive"

    trail = [a.details for a in db.query(AuditLog).filter(AuditLog.action == AuditAction.FINDING_REJECT)]
    assert [d.get("reject_reason") for d in trail] == [None, "artifact", "false_positive"]


def test_reason_in_one_call_and_dashboard_counts(client, findings, db):
    client.post(f"/findings/{findings[0].id}/reject", json={"reason": "artifact"}, headers=_as("dr.a"))
    client.post(f"/findings/{findings[1].id}/reject", json={}, headers=_as("dr.a"))
    d = build_dashboard(db)
    assert d["reject_reasons"] == {REJECT_REASONS["artifact"]: 1, "причина не указана": 1}


def test_guards(client, findings, db):
    f, other = findings[0], findings[1]
    # Свободный текст (мог бы содержать ФИО) не принимается; находка не отклоняется.
    r = client.post(f"/findings/{f.id}/reject", json={"reason": "Иванов, ложное"}, headers=_as("dr.a"))
    assert r.status_code == 422
    db.refresh(f)
    assert f.confirmation_status == ConfirmationStatus.PENDING
    # Уточнить причину неотклонённой находки нельзя.
    assert client.post(f"/findings/{other.id}/reject-reason", json={"reason": "artifact"},
                       headers=_as("dr.a")).status_code == 409
    client.post(f"/findings/{f.id}/reject", json={}, headers=_as("dr.a"))
    # Другой врач не меняет чужое решение; неизвестный код — 422.
    assert client.post(f"/findings/{f.id}/reject-reason", json={"reason": "artifact"},
                       headers=_as("dr.b")).status_code == 409
    assert client.post(f"/findings/{f.id}/reject-reason", json={"reason": "что-то"},
                       headers=_as("dr.a")).status_code == 422
    with pytest.raises(CorrectionError):
        corrections.set_reject_reason(db, finding_id=f.id, physician="dr.a", reason="")


def test_reasons_list_for_ui(client):
    r = client.get("/findings/reject-reasons", headers=_as("dr.a"))
    assert [x["code"] for x in r.json()] == list(REJECT_REASONS)
