"""Неоднозначное сопоставление пациента при приёме (FR-1; файл рисков R-04).

Номер карты есть у нескольких пациентов → исследование не привязывается молча, создаётся
отдельная запись. Раньше это знал только журнал аудита; теперь видит врач (исследование),
администратор (очередь «Требуют сопоставления») и «Состояние системы».
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.imaging import Study
from app.models.patient import Patient, PatientIdentifier
from app.services import patient_admin, system_status
from app.services.anonymization import DeidResult
from app.services.ingest import _get_or_create_patient
from app.services.patient_matching import identifier_value


def _patient(db, mrn: str) -> Patient:
    p = Patient()
    db.add(p)
    db.flush()
    db.add(PatientIdentifier(patient_id=p.id, id_type="mrn", normalized_value=identifier_value("mrn", mrn)))
    db.flush()
    return p


def _plan(mrn: str) -> DeidResult:
    return DeidResult(pseudonym_patient_id=uuid.uuid4(), real_mrn=mrn, real_name=None,
                      real_study_uid=None, pseudonym_study_uid=None)


@pytest.fixture
def ambiguous(db):
    a, b = _patient(db, "MRN-77"), _patient(db, "MRN-77")      # один номер у двух записей
    new, needs_manual = _get_or_create_patient(db, plan=_plan("MRN-77"))
    st = Study(patient_id=new.id, study_instance_uid="1.2.3.77", modality="CR")
    db.add(st)
    db.commit()
    return a, b, new, st, needs_manual


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


H = {"X-Debug-Subject": "adm", "X-Debug-Roles": "admin"}


def test_unique_match_is_not_flagged(db):
    a = _patient(db, "MRN-1")
    p, needs_manual = _get_or_create_patient(db, plan=_plan("MRN-1"))
    assert p.id == a.id and not needs_manual and not p.link_review


def test_ambiguous_creates_flagged_record_with_candidates(ambiguous):
    a, b, new, _, needs_manual = ambiguous
    assert needs_manual and new.id not in (a.id, b.id)
    assert new.link_review and sorted(new.link_candidates) == sorted([str(a.id), str(b.id)])


def test_doctor_sees_warning_on_study(client, ambiguous):
    *_, st, _ = ambiguous
    r = client.get(f"/studies/{st.id}", headers={"X-Debug-Subject": "dr", "X-Debug-Roles": "radiologist"})
    assert r.status_code == 200 and r.json()["patient_link_review"] is True


def test_queue_merge_resolves(client, db, ambiguous):
    a, b, new, st, _ = ambiguous
    q = client.get("/patients/link-review", headers=H).json()
    assert len(q) == 1 and q[0]["patient"]["id"] == str(new.id)
    assert {c["id"] for c in q[0]["candidates"]} == {str(a.id), str(b.id)}
    # Кандидат b позже слит в a — в очереди показывается действующая запись a, без дублей.
    patient_admin.merge_patients(db, source_id=b.id, target_id=a.id, actor="adm")
    db.commit()
    assert [c["id"] for c in client.get("/patients/link-review", headers=H).json()[0]["candidates"]] == [str(a.id)]

    r = client.post("/patients/merge", json={"source_id": str(new.id), "target_id": str(a.id)}, headers=H)
    assert r.status_code == 200
    assert client.get("/patients/link-review", headers=H).json() == []
    db.refresh(st)
    assert st.patient_id == a.id
    assert client.get(f"/studies/{st.id}", headers=H).json()["patient_link_review"] is False


def test_keep_separate_and_roles(client, ambiguous):
    *_, new, _st, _ = ambiguous
    for role in ("clinician", "researcher", "auditor"):
        hdr = {"X-Debug-Subject": "x", "X-Debug-Roles": role}
        assert client.get("/patients/link-review", headers=hdr).status_code == 403
        assert client.post(f"/patients/{new.id}/keep-separate", headers=hdr).status_code == 403
    r = client.post(f"/patients/{new.id}/keep-separate", headers=H)
    assert r.status_code == 200 and r.json()["link_review"] is False
    assert client.post(f"/patients/{new.id}/keep-separate", headers=H).status_code == 409   # уже разобрано
    assert client.get("/patients/link-review", headers=H).json() == []


def test_system_status_warns(db, ambiguous):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    ok, detail, warn = system_status.check_patient_links(lambda: _Ctx())
    assert ok and warn and detail == "ждут сопоставления: 1"
    patient_admin.keep_separate(db, patient_id=ambiguous[2].id, actor="adm")
    assert system_status.check_patient_links(lambda: _Ctx())[2] is False
