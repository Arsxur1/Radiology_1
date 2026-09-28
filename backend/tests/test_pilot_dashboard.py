"""Сводная панель пилота и учёт отказов ИИ (SR-7, FR-11)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.ml import AiRefusal, Finding, ModelStatus
from app.services import classification, corrections
from app.services.pilot_dashboard import build_dashboard
from app.services.segmentation import ApplicabilityRefused

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed_demo import seed  # noqa: E402
from test_classification import PROBS, FixedModel, _model, _series  # noqa: E402


def test_refusal_is_recorded_without_result(db):
    series, mv = _series(db, age=40), _model(db)
    with pytest.raises(ApplicabilityRefused):
        classification.classify_series(db, series=series, model_version=mv, model=FixedModel(PROBS))
    refusals = db.query(AiRefusal).all()
    assert len(refusals) == 1 and "возраст" in refusals[0].reasons[0].lower()
    assert db.query(Finding).count() == 0


def test_dashboard_on_demo_data(db):
    seed(db)
    cxr = [f for f in db.query(Finding).all() if (f.code or "").startswith("CXR-")
           and not f.inference_result.shadow_run]
    corrections.confirm_finding(db, finding_id=cxr[0].id, physician="dr")
    corrections.reject_finding(db, finding_id=cxr[1].id, physician="dr")
    adult_series = _series(db, age=40, uid="adult")
    peds = next(m for m in db.query(classification.ModelVersion).all()
                if m.task == "classification" and m.status == ModelStatus.ACTIVE)
    with pytest.raises(ApplicabilityRefused):
        classification.classify_series(db, series=adult_series, model_version=peds, model=FixedModel(PROBS))

    d = build_dashboard(db, weeks=4, now=datetime.now(UTC))
    t = d["totals"]
    assert t["studies"] == 4 and t["pediatric_studies"] == 1 and t["adult_studies"] == 3
    assert t["physician_decisions"] == 2 and t["ai_refusals"] == 1
    assert len(d["weeks"]) == 4 and sum(d["weekly"]["studies"]) == 4    # всё создано на этой неделе
    assert d["ai_drafts"]["confirmed"] == 1 and d["ai_drafts"]["rejected"] == 1
    assert d["ai_drafts"]["acceptance_rate"] == 0.5
    assert d["refusal_reasons"] == {"возраст": 1}
    assert d["training_data"]["records"] == 1 and d["training_data"]["populations"] == {"pediatric": 1}
    assert [m["model"] for m in d["shadow_models"]] == ["demo_cxr_peds@0.2.0"]
    assert "patient_id" not in str(d)                                    # только агрегаты
