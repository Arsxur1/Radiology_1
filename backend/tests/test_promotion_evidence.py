"""Гейт продвижения на свидетельствах, собранных сервером (FR-10, раздел 9).

Администратор не вводит цифры сам: доля расхождений и срезы берутся из теневого
прогона, объём и результат замороженного теста — из отчёта evaluate на весах кандидата.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.ml import ModelStatus
from app.services import classification, corrections, model_registry
from app.services.model_registry import EvidenceError, PromotionCriteria
from tests.test_classification import PROBS, FixedModel, _finalize, _model, _series

SMALL = PromotionCriteria(min_shadow_cases=4, min_slice_cases=2)


def _frozen(weights="w", n=150, auroc=0.85, digest="d1"):
    return {"weights_hash": weights, "frozen_digest": digest, "n": n, "mean_auroc": auroc,
            "auroc": {"CXR-200": auroc}, "evaluated_at": "2026-09-30T00:00:00+00:00"}


def _shadow_cases(db, mv, *, agree: int, disagree: int, manufacturer="Philips", age=5.0, prefix="x"):
    """Теневой прогон ставит черновик CXR-200; врач соглашается или ставит другую находку."""
    for i in range(agree + disagree):
        s = _series(db, uid=f"{prefix}{i}", manufacturer=manufacturer, age=age)
        classification.classify_series(db, series=s, model_version=mv, model=FixedModel(PROBS))
        code = "CXR-200" if i < agree else "CXR-104"
        corrections.create_physician_finding(db, series_id=s.id, physician="dr", measurements={}, code=code)
        _finalize(db, s)


def test_frozen_evaluation_only_for_own_weights(db):
    mv = _model(db, status=ModelStatus.SHADOW)
    with pytest.raises(EvidenceError, match="других весах"):
        model_registry.record_frozen_evaluation(db, mv, _frozen(weights="other"), actor="admin")
    with pytest.raises(EvidenceError, match="нет полей"):
        model_registry.record_frozen_evaluation(db, mv, {"weights_hash": "w"}, actor="admin")
    model_registry.record_frozen_evaluation(db, mv, _frozen(), actor="admin")
    assert mv.evidence["frozen_test"]["n"] == 150


def test_no_evidence_blocks_promotion(db):
    mv = _model(db, status=ModelStatus.SHADOW)
    gate, ev = model_registry.gate_for(db, mv)
    assert not gate.ok
    assert ev["frozen_test_cases"] == 0 and ev["shadow_rejection_rate"] is None
    text = " ".join(gate.reasons + ev["notes"])
    assert "Замороженный тест: 0" in text and "проверено врачом 0" in text


def test_good_candidate_passes_on_server_evidence(db):
    mv = _model(db, status=ModelStatus.SHADOW)
    model_registry.record_frozen_evaluation(db, mv, _frozen(), actor="admin")
    _shadow_cases(db, mv, agree=9, disagree=1)
    gate, ev = model_registry.gate_for(db, mv, SMALL)
    assert gate.ok, gate.reasons
    assert ev["shadow_rejection_rate"] == pytest.approx(0.1) and ev["shadow_reviewed_cases"] == 10
    assert ev["frozen_test_superior"] is True      # действующей модели нет


def test_pediatric_age_group_degradation_blocks(db):
    """Взрослые в порядке, а на младенцах модель расходится с врачами — продвигать нельзя."""
    mv = _model(db, status=ModelStatus.SHADOW)
    mv.applicability = {**mv.applicability, "age": {"min_years": 0}}
    model_registry.record_frozen_evaluation(db, mv, _frozen(), actor="admin")
    _shadow_cases(db, mv, agree=10, disagree=0, age=40.0, prefix="adult")
    _shadow_cases(db, mv, agree=0, disagree=3, age=0.5, prefix="baby")
    gate, ev = model_registry.gate_for(db, mv, PromotionCriteria(min_shadow_cases=4, min_slice_cases=3,
                                                                 max_rejection_rate=0.25))
    assert ev["shadow_rejection_rate"] == pytest.approx(3 / 13)   # в целом ниже порога…
    assert not gate.ok
    assert any("Возрастная группа «0–1 год»" in r for r in gate.reasons)   # …но не у младенцев


def test_manufacturer_degradation_blocks(db):
    mv = _model(db, status=ModelStatus.SHADOW)
    model_registry.record_frozen_evaluation(db, mv, _frozen(), actor="admin")
    _shadow_cases(db, mv, agree=10, disagree=0, manufacturer="Philips", prefix="p")
    _shadow_cases(db, mv, agree=0, disagree=2, manufacturer="Shimadzu", prefix="s")
    gate, _ = model_registry.gate_for(db, mv, PromotionCriteria(min_shadow_cases=4, min_slice_cases=2,
                                                                max_rejection_rate=0.25))
    assert any("Аппарат «Shimadzu»" in r for r in gate.reasons)


def test_must_beat_active_on_same_frozen_test(db):
    active = _model(db, status=ModelStatus.ACTIVE)
    active.weights_hash = "old"
    model_registry.record_frozen_evaluation(db, active, _frozen(weights="old", auroc=0.88), actor="admin")
    cand = _model(db, status=ModelStatus.SHADOW)
    model_registry.record_frozen_evaluation(db, cand, _frozen(auroc=0.86), actor="admin")
    _shadow_cases(db, cand, agree=10, disagree=0)
    gate, ev = model_registry.gate_for(db, cand, SMALL)
    assert ev["frozen_test_superior"] is False and not gate.ok
    cand.evidence = {"frozen_test": {**cand.evidence["frozen_test"], "frozen_digest": "другой"}}
    _, ev = model_registry.gate_for(db, cand, SMALL)
    assert any("том же замороженном тесте" in n for n in ev["notes"])
    model_registry.record_frozen_evaluation(db, cand, _frozen(auroc=0.90), actor="admin")
    gate, ev = model_registry.gate_for(db, cand, SMALL)
    assert gate.ok and ev["active_model"] == "cxr_peds@0.1.0"


def test_api_ignores_client_numbers_and_records_evidence(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    monkeypatch.setattr(model_registry, "PromotionCriteria", lambda: SMALL)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app, raise_server_exceptions=False)
        h = {"X-Debug-Subject": "admin", "X-Debug-Roles": "admin"}
        mv = _model(db, status=ModelStatus.SHADOW)
        db.commit()
        # Попытка «подсказать» гейту цифры игнорируется: их больше нет в API.
        r = c.post(f"/models/{mv.id}/promote", headers=h,
                   json={"justification": "ок", "frozen_test_cases": 999, "frozen_test_superior": True,
                         "shadow_rejection_rate": 0.0, "no_regression_on_new_devices": True})
        assert r.status_code == 409
        assert c.post(f"/models/{mv.id}/frozen-evaluation", headers=h, json=_frozen(weights="x")).status_code == 422
        assert c.post(f"/models/{mv.id}/frozen-evaluation", headers=h, json=_frozen()).status_code == 200
        _shadow_cases(db, mv, agree=5, disagree=0)
        db.commit()
        ev = c.post(f"/models/{mv.id}/evaluate", headers=h).json()
        assert ev["ok"] is True and ev["evidence"]["shadow_reviewed_cases"] == 5
        r = c.post(f"/models/{mv.id}/promote", headers=h, json={"justification": "Локальная валидация пройдена"})
        assert r.status_code == 200 and r.json()["status"] == "active"
        row = [a for a in db.query(AuditLog).all() if (a.details or {}).get("event") == "promote"][0]
        assert row.details["evidence"]["shadow_reviewed_cases"] == 5
    finally:
        app.dependency_overrides.clear()


def _miss_cases(db, mv, n, *, age=5.0, prefix="m"):
    """Модель ставит CXR-200, а врач находит CXR-200 и ещё CXR-104, которую модель пропустила."""
    for i in range(n):
        s = _series(db, uid=f"{prefix}{i}", age=age)
        classification.classify_series(db, series=s, model_version=mv, model=FixedModel(PROBS))
        for code in ("CXR-200", "CXR-104"):
            corrections.create_physician_finding(db, series_id=s.id, physician="dr", measurements={}, code=code)
        _finalize(db, s)


def test_high_miss_rate_blocks_even_without_false_drafts(db):
    """Черновики модели все верны (расхождений 0 %), но половину находок врача она пропускает."""
    mv = _model(db, status=ModelStatus.SHADOW)
    model_registry.record_frozen_evaluation(db, mv, _frozen(), actor="admin")
    _miss_cases(db, mv, 6)
    gate, ev = model_registry.gate_for(db, mv, SMALL)
    assert ev["shadow_rejection_rate"] == 0 and ev["shadow_miss_rate"] == pytest.approx(0.5)
    assert not gate.ok
    assert any("Доля пропусков модели" in r for r in gate.reasons)
    assert any("Возрастная группа «5–12 лет»: доля пропусков 50%" in r for r in gate.reasons)
    # Порог согласуется с врачами: при допустимых 60 % тот же кандидат проходит.
    assert model_registry.gate_for(db, mv, PromotionCriteria(min_shadow_cases=4, min_slice_cases=2,
                                                             max_miss_rate=0.6))[0].ok


def test_unassessed_sensitivity_blocks(db):
    """Врач ни разу не нашёл ничего из словаря модели — чувствительность не оценить, продвигать нельзя."""
    mv = _model(db, status=ModelStatus.SHADOW)
    model_registry.record_frozen_evaluation(db, mv, _frozen(), actor="admin")
    for i in range(5):
        s = _series(db, uid=f"n{i}")
        classification.classify_series(db, series=s, model_version=mv, model=FixedModel({"CXR-000": 0.9}))
        _finalize(db, s)
    gate, ev = model_registry.gate_for(db, mv, SMALL)
    assert ev["shadow_miss_unassessed"] is True and not gate.ok
    assert any("Пропуски модели не оценены" in r for r in gate.reasons)
