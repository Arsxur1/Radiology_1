"""Готовность данных площадки: возраст, область, кодировка по аппаратам (пилот, SR-7)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.imaging import Study
from app.models.patient import Patient
from app.services.site_data_report import MIN_DESCRIPTION_COUNT, build_site_data_report


def _study(db, patient, **kw):
    fields = dict(modality="DX", manufacturer="Philips", manufacturer_model="DigitalDiagnost",
                  body_part="CHEST", description="Рентгенография ОГК", patient_age_years=6.0)
    fields.update(kw)
    db.add(Study(patient_id=patient.id, study_instance_uid=f"2.25.{uuid.uuid4().int}", **fields))


def _site(db):
    p = Patient()
    db.add(p)
    db.flush()
    for _ in range(20):                      # хороший аппарат: всё передаёт
        _study(db, p)
    for i in range(10):                      # аппарат без тега области, без возраста, cp1251
        _study(db, p, manufacturer="Сибирь", manufacturer_model="R-1", body_part=None,
               description="Кисть 2 проекции" if i < 6 else "ОГК прямая",
               patient_age_years=None if i < 5 else 3.0, charset_guessed="cp1251")
    _study(db, p, manufacturer="Сибирь", manufacturer_model="R-1", body_part=None,
           description="Иванов И.И. 12345", patient_age_years=3.0)   # редкая строка с ФИО
    db.commit()


def test_report_by_device_and_issues(db):
    _site(db)
    r = build_site_data_report(db)
    assert r["studies"] == 31 and not r["ready"]
    good, bad = r["per_device"][0], r["per_device"][1]
    assert good["device"] == "Philips · DigitalDiagnost"
    assert good["age_share"] == good["body_part_share"] == good["region_share"] == 1.0
    assert bad["device"] == "Сибирь · R-1" and bad["studies"] == 11
    assert bad["body_part_share"] == 0 and bad["charset_guessed"] == 10
    assert round(bad["age_share"], 2) == round(6 / 11, 2)
    assert round(bad["region_share"], 2) == round(4 / 11, 2)       # «ОГК» распознаётся по описанию
    assert r["region_source"] == {"body_part": 20, "описание": 4, "не распознано": 7}
    assert r["charset_guessed"] == {"cp1251": 10}
    text = " ".join(r["issues"])
    assert "Сибирь · R-1" in text and "PatientAge" in text and "SpecificCharacterSet" in text
    assert "Philips" not in text                                      # у хорошего аппарата замечаний нет


def test_unrecognized_descriptions_are_safe_to_share(db):
    _site(db)
    r = build_site_data_report(db)
    texts = [d["text"] for d in r["unrecognized_descriptions"]]
    assert texts == ["Кисть # проекции"]                      # цифры скрыты
    assert r["unrecognized_descriptions"][0]["studies"] == 6 >= MIN_DESCRIPTION_COUNT
    assert not any("Иванов" in t for t in texts)                      # редкая строка не показывается
    assert r["rare_unrecognized_studies"] == 1


def test_clean_site_is_ready_and_empty_is_not(db):
    assert build_site_data_report(db)["ready"] is False
    p = Patient()
    db.add(p)
    db.flush()
    for _ in range(3):
        _study(db, p)
    db.commit()
    r = build_site_data_report(db)
    assert r["ready"] is True and r["issues"] == []


def test_endpoint_roles(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        h = {"X-Debug-Subject": "u", "X-Debug-Roles": "radiologist"}
        assert c.get("/pilot/site-data", headers=h).status_code == 403
        h["X-Debug-Roles"] = "auditor"
        assert c.get("/pilot/site-data?days=30", headers=h).json()["days"] == 30
    finally:
        app.dependency_overrides.clear()
