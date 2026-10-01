"""Маркировка участия ИИ в заключении (закон РУз ЗРУ-1115 от 21.01.2026).

Подписанное заключение, в которое вошли находки модели, говорит об этом явно: в печатной
форме (общая отметка и пометка у каждого пункта) и в DICOM SR для PACS (коды алгоритма
DCM 111001/111003 и пояснение). Заключение только из находок врача — без отметки.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes_reports import _export_input
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.ml import Finding, Report
from app.services import classification, corrections
from app.services.report_export import SrIdentity, build_dicom_sr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_classification import FixedModel, _model, _series  # noqa: E402


def _signed(db, *, with_ai: bool, language="ru"):
    series = _series(db, uid=f"s-{with_ai}-{language}")
    sentence_map, text = {}, []
    if with_ai:
        out = classification.classify_series(db, series=series, model_version=_model(db),
                                             model=FixedModel({"CXR-000": 0.1, "CXR-200": 0.9}))
        ai = db.get(Finding, out.finding_ids[0])
        corrections.confirm_finding(db, finding_id=ai.id, physician="dr")
        sentence_map["0"] = str(ai.id)
        text.append("Плевральный выпот")
    own = corrections.create_physician_finding(db, series_id=series.id, physician="dr", measurements={},
                                               code="CXR-201")
    sentence_map[str(len(text))] = str(own.id)
    text.append("Пневмоторакс")
    r = Report(study_id=series.study_id, language=language, finalized_by="dr",
               draft_text=". ".join(text) + ".", sentence_map=sentence_map)
    db.add(r)
    db.commit()
    return r


def test_html_marks_ai_and_items(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        h = {"X-Debug-Subject": "dr", "X-Debug-Roles": "radiologist"}
        page = c.get(f"/reports/{_signed(db, with_ai=True).id}/export.html", headers=h).text
        assert "использована система искусственного интеллекта medviz (cxr_peds 0.1.0)" in page
        assert "(ИИ → подтверждено врачом)" in page and "(врач)" in page
        assert "<h1>Заключение</h1>" in page                       # подписанное — не «черновик»
        own_only = c.get(f"/reports/{_signed(db, with_ai=False).id}/export.html", headers=h).text
        assert "искусственного интеллекта" not in own_only and "(врач)" in own_only
    finally:
        app.dependency_overrides.clear()


def test_sr_carries_algorithm_codes(db):
    report = _signed(db, with_ai=True, language="uz")
    data = _export_input(db, report, "2.25.1")
    assert data.item_origin == {"0": "ai", "1": "physician"} and data.ai_models == ("cxr_peds 0.1.0",)
    ds = build_dicom_sr(data, SrIdentity(patient_id="X", patient_name="X", study_instance_uid="1.2.3"),
                        report_id=str(report.id), verified_at=datetime(2026, 10, 1, tzinfo=UTC), study_date=None)
    items = {(i.ConceptNameCodeSequence[0].CodeValue, i.TextValue) for i in ds.ContentSequence}
    assert ("111001", "medviz: cxr_peds") in items and ("111003", "0.1.0") in items
    comment = [t for code, t in items if code == "121106"]
    assert comment and "sun'iy intellekt" in comment[0]          # язык заключения — узбекский
    own = _signed(db, with_ai=False)
    ds2 = build_dicom_sr(_export_input(db, own, "2.25.2"), SrIdentity("X", "X", "1.2.4"),
                         report_id=str(own.id), verified_at=datetime(2026, 10, 1, tzinfo=UTC), study_date=None)
    assert not any(i.ConceptNameCodeSequence[0].CodeValue in ("111001", "121106") for i in ds2.ContentSequence)
