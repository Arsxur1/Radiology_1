"""Юзабилити (IEC 62366): данные для проверки допущений файла рисков R-01 и R-03."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_classification import FixedModel, _finalize, _model, _series  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.audit import AuditAction  # noqa: E402
from app.models.ml import ModelStatus, Report  # noqa: E402
from app.services import audit, classification, corrections  # noqa: E402
from app.services.usability_metrics import MIN_DECISIONS, build_usability  # noqa: E402

PROBS = {"CXR-200": 0.9, "CXR-500": 0.9, "CXR-104": 0.1}


def _drafts(db, mv, uid):
    s = _series(db, uid=uid)
    out = classification.classify_series(db, series=s, model_version=mv, model=FixedModel(PROBS))
    return s, out.finding_ids


def test_fast_confirmations_and_decision_times(db):
    mv = _model(db, status=ModelStatus.ACTIVE)
    for i in range(MIN_DECISIONS // 2):
        _, (a, b) = _drafts(db, mv, f"u{i}")
        # Половина подтверждений — за секунду (подозрение на автоматическое доверие).
        corrections.confirm_finding(db, finding_id=a, physician="dr", time_spent_seconds=1.0 if i % 2 else 12.0)
        corrections.reject_finding(db, finding_id=b, physician="dr", time_spent_seconds=4.0)
    db.commit()
    u = build_usability(db)
    assert u["ai_decisions"] == {"total": 30, "accepted": 15, "modified": 0, "rejected": 15}
    assert u["fast_confirm"]["count"] == 7 and u["fast_confirm"]["share"] == round(7 / 15, 4)
    assert u["decision_seconds"]["accepted"]["median"] == 12.0
    assert u["decision_seconds"]["rejected"] == {"n": 15, "median": 4.0, "p10": 4.0, "p90": 4.0}
    assert any("автоматическое доверие" in n for n in u["notes"])


def test_few_decisions_are_not_a_conclusion(db):
    mv = _model(db, status=ModelStatus.ACTIVE)
    _, (a, _b) = _drafts(db, mv, "few")
    corrections.confirm_finding(db, finding_id=a, physician="dr", time_spent_seconds=0.5)
    db.commit()
    u = build_usability(db)
    assert any("пока не вывод" in n for n in u["notes"])
    assert not any("автоматическое доверие" in n for n in u["notes"])


def test_shadow_drafts_are_not_counted(db):
    mv = _model(db, status=ModelStatus.SHADOW)
    s = _series(db, uid="sh")
    classification.classify_series(db, series=s, model_version=mv, model=FixedModel(PROBS))
    _finalize(db, s)
    db.commit()
    u = build_usability(db)
    assert u["ai_decisions"]["total"] == 0
    assert u["independent_reading"]["signed_with_ai_drafts"] == 0
    assert any("SHADOW" in n for n in u["notes"])


def test_independent_reading_and_turnaround(db):
    mv = _model(db, status=ModelStatus.ACTIVE)
    # Без черновиков ИИ: в одном врач нашёл своё, в другом — нет.
    for uid, own in (("e1", True), ("e2", False)):
        s = _series(db, uid=uid)
        if own:
            corrections.create_physician_finding(db, series_id=s.id, physician="dr", measurements={},
                                                 code="CXR-200")
        _finalize(db, s)
    # С черновиком ИИ — врач подтвердил и подписал; подпись через 2 часа после приёма.
    s, (a, b) = _drafts(db, mv, "d1")
    corrections.confirm_finding(db, finding_id=a, physician="dr", time_spent_seconds=8.0)
    corrections.reject_finding(db, finding_id=b, physician="dr", time_spent_seconds=8.0)
    _finalize(db, s)
    rep = db.query(Report).filter(Report.study_id == s.study_id).one()
    s.study.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
    audit.record(db, actor="dr", action=AuditAction.REPORT_FINALIZE, entity_type="report", entity_id=rep.id)
    db.commit()
    r = build_usability(db)["independent_reading"]
    assert r == {"signed_studies": 3, "signed_with_ai_drafts": 1, "signed_without_ai_drafts": 2,
                 "own_findings_share_without_drafts": 0.5, "own_findings_share_with_drafts": 0.0}
    assert abs(build_usability(db)["turnaround_hours"]["median"] - 2.0) < 0.1


def test_endpoint_roles(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        assert c.get("/pilot/usability", headers={"X-Debug-Subject": "a", "X-Debug-Roles": "auditor"}).status_code == 200
        assert c.get("/pilot/usability", headers={"X-Debug-Subject": "r", "X-Debug-Roles": "radiologist"}
                     ).status_code == 403
    finally:
        app.dependency_overrides.clear()
