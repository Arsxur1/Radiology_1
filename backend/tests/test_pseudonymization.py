"""Ключевая псевдонимизация (SR-9): в доверенном контуре нет номера карты и ФИО даже в виде
необратимого без ключа хеша; пациенты по-прежнему связываются; без ключа приём стоит."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import pseudonym
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.idmap import IdMapBase, PatientPseudonymMap
from app.models.imaging import Study
from app.models.patient import PatientIdentifier
from app.services import ingest
from app.services.anonymization import anonymize_dataset
from app.workers.dicom_meta import extract_series_meta, extract_study_meta

MRN, NAME_CYR, NAME_LAT = "NCMC-004217", "Алиева^Дилноза", "Aliyeva^Dilnoza^^"


@pytest.fixture
def idmap():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    IdMapBase.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _dataset(name: str) -> Dataset:
    ds = Dataset()
    ds.SpecificCharacterSet = "ISO_IR 192"
    ds.PatientID, ds.PatientName = MRN, name
    ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.SOPInstanceUID = generate_uid(), generate_uid(), generate_uid()
    ds.Modality, ds.StudyDate, ds.PatientAge = "DX", "20261001", "006Y"
    return ds


def _ingest(db, idmap, name: str):
    clean, plan = anonymize_dataset(_dataset(name))
    tags = {e.keyword: str(e.value) for e in clean if e.keyword}
    out = ingest.persist_ingest(db, idmap, plan=plan, study_meta=extract_study_meta(tags),
                                series_meta=extract_series_meta(tags))
    db.commit()
    idmap.commit()
    return clean, plan, out


def test_no_mrn_or_name_in_trusted_contour_and_patients_still_link(db, idmap):
    c1, plan, o1 = _ingest(db, idmap, NAME_CYR)
    _, _, o2 = _ingest(db, idmap, NAME_LAT)          # то же лицо, ФИО латиницей
    assert o1.patient_id == o2.patient_id             # связаны по токену номера карты
    values = [i.normalized_value for i in db.query(PatientIdentifier).all()]
    assert values and all(v.startswith(pseudonym.TOKEN_PREFIX) for v in values)
    blob = " ".join(values).lower()
    for secret in ("004217", "ncmc", "alieva", "aliyeva", "dilnoza", "алиева"):
        assert secret not in blob
    # Реальные данные — только в идентифицирующем контуре.
    assert {r.real_mrn for r in idmap.query(PatientPseudonymMap).all()} == {MRN}
    # Псевдоним в обезличенном DICOM нельзя получить хешем без ключа (раньше было можно).
    unkeyed = uuid.UUID(bytes=hashlib.sha256(f"|{MRN}".encode()).digest()[:16]).hex
    assert c1.PatientID == plan.pseudonym_patient_id.hex != unkeyed
    assert str(c1.PatientName).startswith("ANON^")


def test_key_changes_everything_and_is_required(monkeypatch):
    a = anonymize_dataset(_dataset(NAME_CYR))[1]
    monkeypatch.setattr(get_settings(), "pseudonym_key", "another-key-0123456789abcdef0123456789")
    b = anonymize_dataset(_dataset(NAME_CYR))[1]
    assert a.pseudonym_patient_id != b.pseudonym_patient_id
    monkeypatch.setattr(get_settings(), "pseudonym_key", "")
    with pytest.raises(pseudonym.PseudonymKeyMissing):
        anonymize_dataset(_dataset(NAME_CYR))
    assert pseudonym.key_state()[0] is False
    monkeypatch.setattr(get_settings(), "pseudonym_key", "change_me_pseudonym_key_0123456789")
    assert pseudonym.key_state()[0] is False


def test_search_by_mrn_or_name_returns_tokens_only(db, idmap, monkeypatch):
    _, _, out = _ingest(db, idmap, NAME_CYR)
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        h = {"X-Debug-Subject": "dr", "X-Debug-Roles": "radiologist"}
        # ФИО ищется в той же нормализации, что при приёме (регистр, «^»/пробел, кириллица→латиница);
        # другие варианты транслитерации («Aliyeva» вместо «Alieva») точный токен не найдёт.
        for query in (MRN, " ncmc-004217 ", "Алиева Дилноза", "alieva dilnoza", "АЛИЕВА^ДИЛНОЗА"):
            found = c.get("/patients/search/by-identifier", params={"value": query}, headers=h).json()
            assert [p["id"] for p in found] == [str(out.patient_id)], query
            assert all(i["normalized_value"].startswith("h1:") for i in found[0]["identifiers"])
        assert c.get("/patients/search/by-identifier", params={"value": "NCMC-000001"}, headers=h).json() == []
    finally:
        app.dependency_overrides.clear()
    assert db.query(Study).count() == 1
