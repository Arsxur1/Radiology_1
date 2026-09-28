"""Калибровка порогов по заключениям площадки → новый кандидат в SHADOW (FR-10, SR-3)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_classification import FixedModel, _finalize, _model, _series  # noqa: E402

from app.models.ml import ModelStatus  # noqa: E402
from app.services import classification, corrections  # noqa: E402
from app.services.calibration import CalibrationError, calibration_proposal, register_calibrated  # noqa: E402


def _site(db, n=40):
    mv = _model(db)                                   # порог CXR-200 = 0.5
    for i in range(n):
        positive = i % 3 == 0
        s = _series(db, uid=f"c{i}")
        # Модель «занижает» выпот на этой площадке: у позитивов 0.35, у негативов 0.1.
        probs = {"CXR-200": 0.35 if positive else 0.1, "CXR-500": 0.2, "CXR-104": 0.2}
        classification.classify_series(db, series=s, model_version=mv, model=FixedModel(probs))
        if positive:
            corrections.create_physician_finding(db, series_id=s.id, physician="dr", measurements={},
                                                 code="CXR-200")
        _finalize(db, s)
    return mv


def test_proposal_uses_signed_cases_and_holds_out_test(db):
    mv = _site(db)
    p = calibration_proposal(db, mv.id, min_pos=3, min_neg=3)
    e = p["per_code"]["CXR-200"]
    assert e["current"] == 0.5 and e["proposed"] == 0.35 and e["changed"]
    assert e["sensitivity"] == 1.0 and e["specificity"] == 1.0
    assert p["held_out_test_cases"] > 0 and p["calibration_cases"] + p["held_out_test_cases"] == 40
    assert p["per_code"]["CXR-500"]["changed"] is False         # позитивов нет — порог прежний
    assert p["changed_codes"] == ["CXR-200"]


def test_calibrated_candidate_is_new_shadow_version(db):
    mv = _site(db)
    new = register_calibrated(db, mv.id, actor="admin", min_pos=3, min_neg=3)
    assert new.id != mv.id and new.status == ModelStatus.SHADOW and new.semver == "0.1.1"
    assert new.operating_points["CXR-200"]["threshold"] == 0.35
    assert mv.operating_points["CXR-200"]["threshold"] == 0.5     # действующая модель не изменена
    assert new.weights_hash == mv.weights_hash


def test_not_enough_data(db):
    mv = _model(db)
    with pytest.raises(CalibrationError):
        register_calibrated(db, mv.id, actor="admin")
