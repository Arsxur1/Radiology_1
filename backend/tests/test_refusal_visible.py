"""Отказ ИИ виден врачу на серии (SR-7; файл рисков R-03, R-07).

Без этого в ASSIST пустая серия неотличима: «ИИ посмотрел и не нашёл» или «ИИ не смотрел»
(например, нет возраста или пациент вне границ модели).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_classification import FixedModel, _model, _series  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.audit import OperatingMode, OperatingModeState  # noqa: E402
from app.models.ml import ModelStatus  # noqa: E402
from app.services import classification  # noqa: E402
from app.services.segmentation import ApplicabilityRefused  # noqa: E402

H = {"X-Debug-Subject": "dr", "X-Debug-Roles": "radiologist"}


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _run(db, s, mv):
    try:
        classification.classify_series(db, series=s, model_version=mv, model=FixedModel({"CXR-200": 0.9}))
    except ApplicabilityRefused:
        pass
    db.commit()


def _refusals(client, s):
    body = client.get(f"/studies/{s.study_id}", headers=H).json()
    return body["series"][0]["ai_refusals"]


def test_active_model_refusal_is_shown_with_reason(client, db):
    mv = _model(db, status=ModelStatus.ACTIVE)
    s = _series(db, uid="adult", age=40.0)                 # модель детская — взрослый вне границ
    _run(db, s, mv)
    r = _refusals(client, s)
    assert len(r) == 1 and r[0]["model"] == f"{mv.name}@{mv.semver}" and r[0]["reasons"]


def test_refusal_cleared_after_successful_run(client, db):
    mv = _model(db, status=ModelStatus.ACTIVE)
    s = _series(db, uid="fixed", age=40.0)
    _run(db, s, mv)
    s.study.patient_age_years = 5.0                         # возраст исправили, повторный анализ прошёл
    _run(db, s, mv)
    assert _refusals(client, s) == []


def test_shadow_candidate_refusal_not_shown(client, db):
    mv = _model(db, status=ModelStatus.SHADOW)
    s = _series(db, uid="sh", age=40.0)
    _run(db, s, mv)
    assert _refusals(client, s) == []


def test_hidden_in_shadow_mode(client, db):
    mv = _model(db, status=ModelStatus.ACTIVE)
    s = _series(db, uid="mode", age=40.0)
    _run(db, s, mv)
    db.add(OperatingModeState(modality="*", mode=OperatingMode.SHADOW, changed_by="adm"))
    db.commit()
    assert _refusals(client, s) == []
