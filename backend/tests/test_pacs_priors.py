"""Предыдущие исследования пациента из PACS: поиск без PHI и выгрузка по токену (FR-1, FR-7)."""

from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("pynetdicom")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_db, get_idmap_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.idmap import IdMapBase, PatientPseudonymMap  # noqa: E402
from app.models.imaging import Study  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from tests.test_pacs_scp import dicom_net  # noqa: E402,F401  фикстура: локальный PACS + приёмник

H = {"X-Debug-Subject": "dr.priors", "X-Debug-Roles": "radiologist"}


@pytest.fixture
def setup(db, monkeypatch, dicom_net):  # noqa: F811
    node, received = dicom_net
    s = get_settings()
    monkeypatch.setattr(s, "allow_debug_auth", True)
    monkeypatch.setattr(s, "pacs_aet", node.aet)
    monkeypatch.setattr(s, "pacs_host", node.host)
    monkeypatch.setattr(s, "pacs_port", node.port)
    monkeypatch.setattr(s, "pacs_local_aet", node.local_aet)
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    IdMapBase.metadata.create_all(eng)
    idmap = sessionmaker(bind=eng)()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_idmap_db] = lambda: idmap

    p = Patient()
    db.add(p)
    db.flush()
    st = Study(patient_id=p.id, study_instance_uid="2.25.10", modality="CT", study_date=datetime(2025, 1, 1))
    db.add(st)
    db.commit()
    idmap.add(PatientPseudonymMap(pseudonym_patient_id=p.id, real_mrn="MRN-7", real_name="Synthetic^Child",
                                  real_study_instance_uid="1.2.826.0.1.1", pseudonym_study_instance_uid="2.25.10"))
    idmap.commit()
    try:
        yield TestClient(app, raise_server_exceptions=False), st, received, s
    finally:
        app.dependency_overrides.clear()


def test_priors_listed_without_phi(setup, db):
    client, st, _, _ = setup
    r = client.get(f"/studies/{st.id}/pacs-priors", headers=H)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [(x["study_date"], x["modality"]) for x in rows] == [("20260315", "MR"), ("20250101", "CT")]
    current = rows[1]
    assert current["is_current"] is True and current["imported_study_id"] == str(st.id)
    assert rows[0]["imported_study_id"] is None
    for leaked in ("MRN-7", "MRN-8", "1.2.826.0.1", "Test^", "Child"):
        assert leaked not in r.text            # ни номера карты, ни исходных UID, ни ФИО
    log = db.query(AuditLog).filter(AuditLog.entity_type == "pacs_priors").all()
    assert len(log) == 1 and log[0].details["found"] == 2


def test_retrieve_by_token_moves_study_to_platform(setup, db):
    client, st, received, _ = setup
    token = client.get(f"/studies/{st.id}/pacs-priors", headers=H).json()[0]["token"]
    r = client.post(f"/studies/{st.id}/pacs-priors/{token}/retrieve", headers=H)
    assert r.status_code == 200, r.text
    assert [d.StudyInstanceUID for d in received] == ["1.2.826.0.1.2"]   # пришло на orthanc-raw
    assert client.post(f"/studies/{st.id}/pacs-priors/{'0' * 32}/retrieve", headers=H).status_code == 404


def test_other_patient_study_cannot_be_retrieved(setup):
    from app.services.pacs_priors import study_token

    client, st, received, _ = setup
    foreign = study_token("1.2.826.0.1.3")        # исследование другого пациента (MRN-8)
    assert client.post(f"/studies/{st.id}/pacs-priors/{foreign}/retrieve", headers=H).status_code == 404
    assert received == []


def test_roles_and_configuration(setup, monkeypatch):
    client, st, _, s = setup
    url = f"/studies/{st.id}/pacs-priors"
    assert client.get(url, headers={**H, "X-Debug-Roles": "researcher"}).status_code == 403
    assert client.get(url, headers={**H, "X-Debug-Roles": "auditor"}).status_code == 403
    monkeypatch.setattr(s, "pacs_host", None)
    r = client.get(url, headers=H)
    assert r.status_code == 503 and "не настроен" in r.json()["detail"]
