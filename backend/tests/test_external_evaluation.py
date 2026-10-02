"""Внешняя детская проверка как свидетельство кандидата (docs/VALIDATSIYA-DETI.md)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.services import model_registry
from app.services.model_registry import EvidenceError

OPS = {"CXR-000": {"threshold": 0.5}, "CXR-200": {"threshold": 0.5}}


def _report(weights_hash: str, auroc: float = 0.64, kind: str = "external_pediatric") -> dict:
    return {"kind": kind, "dataset": "HWCMC (0–14 лет)", "citation": "Yu J. 2024", "source": "Zenodo 13744272",
            "models": {"densenet121-res224-nih": {
                "weights_hash": weights_hash, "n": {"normal": 2291, "total": 5632},
                "any_finding_auroc": auroc, "any_finding_auroc_ci95": [0.62, 0.66],
                "normal_with_any_draft": 0.54, "pneumonia_with_any_draft": 0.76,
                "with_any_draft_by_kind": {"normal": 0.54}, "per_code": {"CXR-200": {}}}}}


@pytest.fixture
def candidate(db):
    m = model_registry.register_candidate(
        db, name="xrv_nih", semver="0.1.0", weights_hash="abc123", applicability={}, actor="adm",
        task="classification", operating_points=OPS, adapter={"type": "xrv", "weights": "densenet121-res224-nih"})
    db.commit()
    return m


def test_accepted_only_for_same_weights(db, candidate):
    with pytest.raises(EvidenceError, match="weights_hash"):
        model_registry.record_external_evaluation(db, candidate, _report("other"), actor="adm")
    with pytest.raises(EvidenceError, match="не отчёт"):
        model_registry.record_external_evaluation(db, candidate, _report("abc123", kind="x"), actor="adm")
    r = model_registry.record_external_evaluation(db, candidate, _report("abc123"), actor="adm")
    assert r["any_finding_auroc"] == 0.64 and "per_code" not in r          # только сводка
    assert candidate.evidence["external_tests"]["HWCMC (0–14 лет)"]["n"]["total"] == 5632


def test_shown_in_evidence_but_does_not_block(db, candidate):
    model_registry.record_external_evaluation(db, candidate, _report("abc123", auroc=0.64), actor="adm")
    gate, ev = model_registry.gate_for(db, candidate)
    note = next(n for n in ev["notes"] if "Внешний детский тест" in n)
    assert "AUROC 0.64" in note and "54% здоровых" in note and "слабая переносимость" in note
    assert not any("Внешний детский тест" in r for r in gate.reasons)
    assert "HWCMC (0–14 лет)" in ev["external_tests"]
    model_registry.record_external_evaluation(db, candidate, _report("abc123", auroc=0.91), actor="adm")
    _, ev = model_registry.gate_for(db, candidate)
    assert not any("слабая переносимость" in n for n in ev["notes"])      # обновился, а не добавился


def test_api(db, candidate, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        h = {"X-Debug-Subject": "adm", "X-Debug-Roles": "admin"}
        url = f"/models/{candidate.id}/external-evaluation"
        assert c.post(url, json=_report("nope"), headers=h).status_code == 422
        assert c.post(url, json=_report("abc123"), headers=h).json()["dataset"] == "HWCMC (0–14 лет)"
        h["X-Debug-Roles"] = "radiologist"
        assert c.post(url, json=_report("abc123"), headers=h).status_code == 403
    finally:
        app.dependency_overrides.clear()
