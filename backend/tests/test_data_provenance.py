"""Происхождение обучающих данных и коммерческое применение (ТЗ, вопрос 34)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.ml import ModelStatus, ModelVersion
from app.services import data_provenance as dp
from app.services import model_registry

OPS = {"CXR-000": {"threshold": 0.5}, "CXR-200": {"threshold": 0.5}}
APPL = {"modality": ["DX"], "body_part": ["CHEST"], "age": {"min_years": 0}}


def test_xrv_weights_provenance():
    allw = dp.assess({"type": "xrv", "weights": "densenet121-res224-all"}, None)
    assert allw["commercial"] == "no"
    assert set(allw["research_only"]) == {"PadChest", "MIMIC-CXR (метки CheXpert)"}
    nih = dp.assess({"type": "xrv", "weights": "densenet121-res224-nih"}, None)
    assert nih["commercial"] == "yes" and nih["training_data"] == ["nih"]
    assert dp.assess({"type": "totalsegmentator", "task": "total"}, None)["commercial"] == "yes"
    # Каждые допустимые веса xrv описаны — новые веса без происхождения не пройдут молча.
    assert set(model_registry.XRV_WEIGHTS) <= set(dp.XRV_TRAINING_DATA)


def test_own_models_by_declared_data():
    assert dp.assess({}, ["vindr-pcxr", "imagenet"])["commercial"] == "no"   # VinDr-PCXR — только исследования
    assert dp.assess({}, ["ncmc"])["commercial"] == "yes"
    assert dp.assess({}, ["ncmc", "imagenet"])["commercial"] == "unknown"
    assert dp.assess({}, ["kakoy-to"])["unverified"] == ["kakoy-to"]
    assert dp.assess({}, None)["commercial"] == "unknown"
    assert dp.gate_reason(dp.assess({}, ["ncmc", "imagenet"])) is None        # неизвестное — к юристу, не блок


def test_gate_blocks_research_only_weights(db):
    def reg(name, adapter=None, training_data=None):
        m = model_registry.register_candidate(db, name=name, semver="1.0.0", weights_hash="h", applicability=APPL,
                                              actor="adm", task="classification", operating_points=OPS,
                                              adapter=adapter, training_data=training_data)
        db.flush()
        return m

    research = reg("xrv_all", {"type": "xrv", "weights": "densenet121-res224-all"})
    gate, ev = model_registry.gate_for(db, research)
    assert not gate.ok and any("только для научных исследований" in r for r in gate.reasons)
    assert ev["data_provenance"]["commercial"] == "no"

    clean = reg("xrv_nih", {"type": "xrv", "weights": "densenet121-res224-nih"})
    gate, ev = model_registry.gate_for(db, clean)
    assert not any("научных исследований" in r for r in gate.reasons)
    assert ev["data_provenance"]["commercial"] == "yes"

    own = reg("cxr_peds", training_data=["ncmc", "imagenet"])
    assert own.evidence["training_data"] == ["ncmc", "imagenet"]
    _, ev = model_registry.gate_for(db, own)
    assert any("юристом" in n for n in ev["notes"])


def test_register_api_keeps_training_data(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        h = {"X-Debug-Subject": "adm", "X-Debug-Roles": "admin"}
        r = c.post("/models/candidates", headers=h, json={
            "name": "cxr_peds", "semver": "2.0.0", "weights_hash": "x", "applicability": APPL,
            "task": "classification", "operating_points": OPS, "training_data": ["vindr-pcxr", "imagenet"]})
        assert r.status_code == 200, r.text
        m = db.get(ModelVersion, __import__("uuid").UUID(r.json()["id"]))
        assert m.status == ModelStatus.SHADOW and m.evidence["training_data"] == ["vindr-pcxr", "imagenet"]
    finally:
        app.dependency_overrides.clear()
