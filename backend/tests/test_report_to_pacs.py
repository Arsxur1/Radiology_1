"""Подписанное заключение уходит в PACS клиники как DICOM SR (FR-8, FR-1).

Проверяется на локальном DICOM-узле: SR лёг к настоящему пациенту и исследованию,
подписан врачом (VERIFIED), текст на кириллице не искажён, повторная отправка
заменяет тот же документ, а в журнале аудита — факт отправки без ФИО.
"""

from __future__ import annotations

import uuid
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
from app.models.ml import Report  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from tests.test_pacs_scp import dicom_net  # noqa: E402,F401

H = {"X-Debug-Subject": "dr.aliyeva", "X-Debug-Roles": "radiologist"}
FINDING = str(uuid.UUID(int=12345))


@pytest.fixture
def setup(db, monkeypatch, dicom_net):  # noqa: F811
    node, _, stored = dicom_net
    s = get_settings()
    for k, v in (("allow_debug_auth", True), ("pacs_aet", node.aet), ("pacs_host", node.host),
                 ("pacs_port", node.port), ("pacs_local_aet", node.local_aet)):
        monkeypatch.setattr(s, k, v)
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    IdMapBase.metadata.create_all(eng)
    idmap = sessionmaker(bind=eng)()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_idmap_db] = lambda: idmap
    p = Patient()
    db.add(p)
    db.flush()
    st = Study(patient_id=p.id, study_instance_uid="2.25.77", modality="DX", study_date=datetime(2026, 9, 29))
    db.add(st)
    db.flush()
    signed = Report(study_id=st.id, language="ru", finalized_by="dr.aliyeva",
                    draft_text="Плевральный выпот справа. Кардиомегалия.", sentence_map={"0": FINDING})
    draft = Report(study_id=st.id, language="ru", draft_text="Черновик.", sentence_map={})
    db.add_all([signed, draft])
    db.commit()
    idmap.add(PatientPseudonymMap(pseudonym_patient_id=p.id, real_mrn="NCMC-4242", real_name="Karimova^Dilnoza",
                                  real_study_instance_uid="1.2.826.0.1.99", pseudonym_study_instance_uid="2.25.77"))
    idmap.commit()
    try:
        yield TestClient(app, raise_server_exceptions=False), signed, draft, stored, s
    finally:
        app.dependency_overrides.clear()


def test_signed_report_lands_in_pacs_with_real_identity(setup, db):
    client, signed, _, stored, _ = setup
    r = client.post(f"/reports/{signed.id}/send-to-pacs", headers=H)
    assert r.status_code == 200, r.text
    assert len(stored) == 1
    sr = stored[0]
    assert sr.SOPClassUID == "1.2.840.10008.5.1.4.1.1.88.11"          # Basic Text SR
    assert sr.PatientID == "NCMC-4242" and str(sr.PatientName) == "Karimova^Dilnoza"
    assert sr.StudyInstanceUID == "1.2.826.0.1.99"                     # исходное исследование в PACS
    assert sr.VerificationFlag == "VERIFIED" and sr.CompletionFlag == "COMPLETE"
    assert str(sr.VerifyingObserverSequence[0].VerifyingObserverName) == "dr.aliyeva"
    texts = [i.TextValue for i in sr.ContentSequence]
    assert texts == ["Плевральный выпот справа.", "Кардиомегалия."]   # UTF-8 без искажений
    assert sr.ContentSequence[0].ObservationUID == "2.25.12345"        # трассировка до находки
    assert "ObservationUID" not in sr.ContentSequence[1]
    # Журнал: факт отправки, но не ФИО и не номер карты.
    row = [a for a in db.query(AuditLog).all() if a.entity_type == "report"][-1]
    assert row.details["ok"] is True
    assert "Karimova" not in str(row.details) and "NCMC-4242" not in str(row.details)


def test_resend_replaces_same_document(setup):
    client, signed, _, stored, _ = setup
    uids = [client.post(f"/reports/{signed.id}/send-to-pacs", headers=H).json()["sop_instance_uid"]
            for _ in range(2)]
    assert uids[0] == uids[1] and stored[0].SOPInstanceUID == stored[1].SOPInstanceUID


def test_guards(setup, monkeypatch):
    client, signed, draft, stored, s = setup
    assert client.post(f"/reports/{draft.id}/send-to-pacs", headers=H).status_code == 409    # не подписано
    for role in ("clinician", "researcher", "auditor"):
        assert client.post(f"/reports/{signed.id}/send-to-pacs",
                           headers={**H, "X-Debug-Roles": role}).status_code == 403
    monkeypatch.setattr(s, "pacs_host", None)
    assert client.post(f"/reports/{signed.id}/send-to-pacs", headers=H).status_code == 503
    assert stored == []


def test_sr_file_roundtrip():
    """SR сериализуется в файл DICOM Part 10 и читается обратно."""
    import io

    from pydicom import dcmread

    from app.services.report_export import ReportExportInput, SrIdentity, build_dicom_sr, sr_bytes

    data = ReportExportInput(study_uid="2.25.1", language="uz", draft_text="", sentence_map={},
                             finalized_by="dr x", sentences=["Oʻng tomonda plevral suyuqlik."])
    ds = build_dicom_sr(data, SrIdentity("MRN", "A^B", "1.2.3"), report_id="r1",
                        verified_at=datetime(2026, 9, 30, 12, 0, 0))
    back = dcmread(io.BytesIO(sr_bytes(ds)))
    assert back.ContentSequence[0].TextValue == "Oʻng tomonda plevral suyuqlik."
    assert back.SeriesDescription == "Xulosa (medviz)" and back.ContentDate == "20260930"
    assert str(back.VerifyingObserverSequence[0].VerifyingObserverName) == "dr^x"


def test_report_loaded_by_study(setup):
    client, signed, _, _, _ = setup
    r = client.get(f"/reports/by-study/{signed.study_id}", headers=H)
    assert r.status_code == 200 and r.json()["finalized_by"] == "dr.aliyeva"   # подписанное важнее черновика
    assert client.get(f"/reports/by-study/{uuid.uuid4()}", headers=H).status_code == 404
    assert client.get(f"/reports/by-study/{signed.study_id}",
                      headers={**H, "X-Debug-Roles": "researcher"}).status_code == 403
