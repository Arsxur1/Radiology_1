"""Рабочий список: фильтры на сервере — неописанное находится среди всех исследований."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.imaging import Study
from app.models.ml import Report
from app.models.patient import Patient

H = {"X-Debug-Subject": "dr", "X-Debug-Roles": "radiologist"}


def _client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


def _seed(db, n=120):
    p = Patient()
    db.add(p)
    db.flush()
    base = datetime(2026, 9, 1)
    ids = []
    for i in range(n):
        st = Study(patient_id=p.id, study_instance_uid=f"2.25.{i}", modality="DX", study_date=base + timedelta(hours=i))
        db.add(st)
        db.flush()
        ids.append(st.id)
        if i % 3:                                   # каждое третье — без подписанного заключения
            db.add(Report(study_id=st.id, draft_text="x", sentence_map={}, finalized_by="dr"))
    db.commit()
    return ids


def test_unsigned_queue_finds_old_studies(db, monkeypatch):
    c = _client(db, monkeypatch)
    try:
        ids = _seed(db)
        # Старое неподписанное (самое первое) не попадает в «последние 50» — но есть в очереди.
        latest = c.get("/studies?limit=50", headers=H)
        assert str(ids[0]) not in {s["id"] for s in latest.json()}
        q = c.get("/studies?status=unsigned&order=asc&limit=10", headers=H)
        assert q.status_code == 200 and q.headers["x-total-count"] == "40"
        assert [s["id"] for s in q.json()][:2] == [str(ids[0]), str(ids[3])]    # старые сверху
        assert all(s["report_status"] != "signed" for s in q.json())
        nxt = c.get("/studies?status=unsigned&order=asc&limit=10&offset=10", headers=H).json()
        assert not {s["id"] for s in nxt} & {s["id"] for s in q.json()}          # страницы не пересекаются
        signed = c.get("/studies?status=signed&limit=500", headers=H)
        assert signed.headers["x-total-count"] == "80"
    finally:
        app.dependency_overrides.clear()


def test_date_range_and_validation(db, monkeypatch):
    c = _client(db, monkeypatch)
    try:
        _seed(db, n=72)                                   # 3 дня по 24 исследования
        day2 = c.get("/studies?date_from=2026-09-02&date_to=2026-09-02&limit=500", headers=H)
        assert day2.headers["x-total-count"] == "24"
        assert {s["study_date"][:10] for s in day2.json()} == {"2026-09-02"}
        assert c.get("/studies?status=everything", headers=H).status_code == 422
        assert c.get("/studies?limit=100000", headers=H).status_code == 422
    finally:
        app.dependency_overrides.clear()
