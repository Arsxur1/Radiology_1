"""Отзыв согласия на использование данных для обучения (цель 2 приложения к договору).

Исследования пациента не идут ни в один путь обучения: выгрузка меток площадки, выгрузка
правок врачей, калибровка порогов. Работа врача и контроль качества не затрагиваются.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_calibration import _site  # noqa: E402
from test_classification import _finalize, _series  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.imaging import Study  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.services import corrections, dataset_export, patient_admin  # noqa: E402
from app.services.calibration import calibration_proposal  # noqa: E402
from app.services.patient_admin import MergeError  # noqa: E402
from app.services.pilot_dashboard import build_dashboard  # noqa: E402
from app.services.site_labels import site_manifest  # noqa: E402


def _labeled(db, uid):
    s = _series(db, uid=uid)
    corrections.create_physician_finding(db, series_id=s.id, physician="dr", measurements={}, code="CXR-200")
    _finalize(db, s)
    return s, db.get(Study, s.study_id).patient_id


def _exclude(db, pid, excluded=True, basis="consent_withdrawn"):
    patient_admin.set_training_exclusion(db, patient_id=pid, excluded=excluded, actor="adm", basis=basis)
    db.commit()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_manifest_export_and_dashboard_skip_excluded(db):
    keep, _ = _labeled(db, "keep")
    gone, pid = _labeled(db, "gone")
    assert {r["image_id"] for r in site_manifest(db)[0]} == {"keep", "gone"}
    assert len(dataset_export.export(db)) == 2

    _exclude(db, pid)
    records, report = site_manifest(db)
    assert {r["image_id"] for r in records} == {"keep"} and report["skipped_training_excluded"] == 1
    assert [i.series_instance_uid for i in dataset_export.export(db)] == ["keep"]
    assert build_dashboard(db)["training_data"]["skipped_training_excluded"] == 1

    _exclude(db, pid, excluded=False, basis="consent_restored")      # согласие получено вновь
    assert len(site_manifest(db)[0]) == 2
    events = [a.details for a in db.query(AuditLog).order_by(AuditLog.seq) if a.details.get("event") ==
              "training_exclusion"]
    assert [(e["excluded"], e["basis"]) for e in events] == [(True, "consent_withdrawn"),
                                                             (False, "consent_restored")]


def test_calibration_skips_excluded(db):
    mv = _site(db)
    before = calibration_proposal(db, mv.id, min_pos=3, min_neg=3)
    for p in db.query(Patient).limit(10):
        _exclude(db, p.id)
    after = calibration_proposal(db, mv.id, min_pos=3, min_neg=3)
    total = lambda p: p["calibration_cases"] + p["held_out_test_cases"]  # noqa: E731
    assert total(before) == 40 and total(after) == 30


def test_merge_and_split_keep_exclusion(db):
    _, a = _labeled(db, "a")
    _, b = _labeled(db, "b")
    _exclude(db, a)
    patient_admin.merge_patients(db, source_id=a, target_id=b, actor="adm")     # исключённый → в b
    assert db.get(Patient, b).training_excluded is True
    st = db.query(Study).filter(Study.patient_id == b).first()
    out = patient_admin.split_patient(db, source_patient_id=b, identifier_ids=[], study_ids=[st.id], actor="adm")
    assert db.get(Patient, out.new_patient_id).training_excluded is True
    assert site_manifest(db)[0] == []


def test_validation_and_api_roles(client, db):
    _, pid = _labeled(db, "x")
    with pytest.raises(MergeError):
        patient_admin.set_training_exclusion(db, patient_id=pid, excluded=True, actor="adm", basis="просто так")
    adm = {"X-Debug-Subject": "adm", "X-Debug-Roles": "admin"}
    assert {b["code"] for b in client.get("/patients/training-exclusion-bases", headers=adm).json()} >= {
        "consent_withdrawn", "consent_restored"}
    url = f"/patients/{pid}/training-exclusion"
    for role in ("radiologist", "clinician", "researcher", "auditor"):
        r = client.post(url, json={"excluded": True, "basis": "consent_withdrawn"},
                        headers={"X-Debug-Subject": "u", "X-Debug-Roles": role})
        assert r.status_code == 403
    r = client.post(url, json={"excluded": True, "basis": "consent_withdrawn"}, headers=adm)
    assert r.status_code == 200 and r.json()["training_excluded"] is True
    assert client.post(url, json={"excluded": True, "basis": "free text"}, headers=adm).status_code == 409
