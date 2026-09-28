"""Классификатор находок ОГК: пороги, теневой прогон, метки площадки (FR-10, SR-1, SR-7)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.api.routes_findings import list_series_findings
from app.models.imaging import Series, Study
from app.models.ml import ConfirmationStatus, Finding, FindingSource, ModelStatus, ModelVersion, Report
from app.models.patient import Patient
from app.services import classification, corrections, model_registry
from app.services.classification import ClassificationModel, ClassificationOutput, WrongModelTask, draft_codes
from app.services.corrections import CorrectionError
from app.services.model_registry import PromotionError
from app.services.report_draft import FindingInput, build_draft
from app.services.segmentation import ApplicabilityRefused
from app.services.shadow_eval import shadow_report
from app.services.site_labels import site_manifest
from app.workers.classification_tasks import classify_with_all

PEDS = {"modality": ["CR", "DX"], "body_part": ["CHEST", "THORAX"],
        "age": {"min_years": 0, "max_years": 10}, "allow_lossy": False}
OPS = {"CXR-000": {"threshold": 0.5}, "CXR-200": {"threshold": 0.5},
       "CXR-500": {"threshold": 0.7}, "CXR-104": {"threshold": 0.5}}


class FixedModel(ClassificationModel):
    def __init__(self, probs: dict[str, float]) -> None:
        self.probs = probs
        self.weights_hash = "w"

    def predict(self, series_object_prefix: str) -> ClassificationOutput:
        return ClassificationOutput(dict(self.probs), {"adapter": "fixed"})


PROBS = {"CXR-000": 0.9, "CXR-200": 0.8, "CXR-500": 0.6, "CXR-104": 0.1, "CXR-999": 0.99}


def _series(db, *, age=5.0, modality="DX", manufacturer="Philips", uid="s1"):
    patient = Patient()
    db.add(patient)
    db.flush()
    study = Study(patient_id=patient.id, study_instance_uid=f"st-{uid}", modality=modality,
                  study_date=datetime(2026, 9, 1), manufacturer=manufacturer,
                  protocol="Chest PA", patient_age_years=age)
    db.add(study)
    db.flush()
    series = Series(study_id=study.id, series_instance_uid=uid, modality=modality,
                    lossy_compressed=False, object_prefix=f"pfx/{uid}")
    db.add(series)
    db.flush()
    return series


def _model(db, status=ModelStatus.ACTIVE, task="classification", name="cxr_peds"):
    mv = ModelVersion(name=name, semver="0.1.0", weights_hash="w", applicability=PEDS,
                      status=status, task=task, operating_points=OPS)
    db.add(mv)
    db.flush()
    return mv


def _finalize(db, series):
    db.add(Report(study_id=series.study_id, draft_text="", finalized_by="dr"))
    db.flush()


# ─── Регистрация ──────────────────────────────────────────────────────────────
def test_register_classifier_requires_valid_operating_points(db):
    kw = dict(name="m", semver="1", weights_hash="h", applicability=PEDS, actor="a", task="classification")
    with pytest.raises(PromotionError):
        model_registry.register_candidate(db, operating_points={}, **kw)
    with pytest.raises(PromotionError):
        model_registry.register_candidate(db, operating_points={"CXR-XXX": {"threshold": 0.5}}, **kw)
    with pytest.raises(PromotionError):
        model_registry.register_candidate(db, operating_points={"CXR-200": {"threshold": 1.5}}, **kw)
    with pytest.raises(PromotionError):
        model_registry.register_candidate(db, operating_points=OPS, **{**kw, "task": "diagnosis"})
    mv = model_registry.register_candidate(db, operating_points=OPS, **kw)
    assert mv.status == ModelStatus.SHADOW and mv.task == "classification"


# ─── Черновики находок ────────────────────────────────────────────────────────
def test_draft_codes_thresholds_and_exclusions():
    drafted = [c for c, _, _ in draft_codes(PROBS, OPS, "DX")]
    # CXR-000 («норма») не черновик; CXR-500 ниже своего порога; CXR-999 вне словаря.
    assert drafted == ["CXR-200"]


def test_active_classification_creates_pending_drafts(db):
    series, mv = _series(db), _model(db)
    out = classification.classify_series(db, series=series, model_version=mv, model=FixedModel(PROBS))
    assert not out.shadow_run and len(out.finding_ids) == 1
    f = db.get(Finding, out.finding_ids[0])
    assert (f.code, f.source, f.confirmation_status) == ("CXR-200", FindingSource.MODEL, ConfirmationStatus.PENDING)
    assert f.measurements == {"confidence": 0.8, "threshold": 0.5}
    assert f.inference_result.metrics["probabilities"]["CXR-500"] == 0.6    # трассировка всех выходов
    assert [x.code for x in list_series_findings(series.id, db)] == ["CXR-200"]


def test_applicability_refusal_for_adult_on_pediatric_model(db):
    series, mv = _series(db, age=40), _model(db)
    with pytest.raises(ApplicabilityRefused):
        classification.classify_series(db, series=series, model_version=mv, model=FixedModel(PROBS))
    assert db.query(Finding).count() == 0


def test_segmentation_model_rejected(db):
    series, mv = _series(db), _model(db, task="segmentation")
    with pytest.raises(WrongModelTask):
        classification.classify_series(db, series=series, model_version=mv, model=FixedModel(PROBS))


# ─── Теневой прогон ───────────────────────────────────────────────────────────
def test_shadow_findings_hidden_and_not_actionable(db):
    series, mv = _series(db), _model(db, status=ModelStatus.SHADOW)
    out = classification.classify_series(db, series=series, model_version=mv, model=FixedModel(PROBS))
    assert out.shadow_run and out.finding_ids
    assert list_series_findings(series.id, db) == []
    with pytest.raises(CorrectionError):
        corrections.confirm_finding(db, finding_id=out.finding_ids[0], physician="dr")
    # После продвижения модели старые теневые находки так и остаются скрытыми.
    mv.status = ModelStatus.ACTIVE
    db.flush()
    assert list_series_findings(series.id, db) == []


def test_models_for_and_worker_runs_active_and_shadow(db):
    active = _model(db)
    shadow = _model(db, status=ModelStatus.SHADOW, name="cxr_peds_next")
    _model(db, task="segmentation", name="seg")
    ct_only = _model(db, name="ct_model")
    ct_only.applicability = {**PEDS, "modality": ["CT"]}
    db.flush()
    found = model_registry.models_for(db, task="classification", modality="DX",
                                      statuses=(ModelStatus.ACTIVE, ModelStatus.SHADOW))
    assert {m.id for m in found} == {active.id, shadow.id}
    result = classify_with_all(db, _series(db), use_stub=True)
    assert sorted(r["shadow"] for r in result["results"]) == [False, True]


# ─── Метки площадки и сравнение теневого прогона ─────────────────────────────
def test_site_manifest_labels(db):
    mv = _model(db)
    s1 = _series(db, uid="s1")
    out = classification.classify_series(db, series=s1, model_version=mv,
                                         model=FixedModel({**PROBS, "CXR-500": 0.9}))
    by_code = {db.get(Finding, i).code: i for i in out.finding_ids}
    corrections.confirm_finding(db, finding_id=by_code["CXR-200"], physician="dr")
    corrections.reject_finding(db, finding_id=by_code["CXR-500"], physician="dr")
    corrections.create_physician_finding(db, series_id=s1.id, physician="dr", measurements={},
                                         code="CXR-104", coding_system="MEDVIZ-CXR")
    s2 = _series(db, uid="s2")                     # подписанная норма
    _finalize(db, s2)
    _series(db, uid="s3")                          # без решений — не используется
    s4 = _series(db, uid="s4", age=None)           # без возраста — не используется
    corrections.create_physician_finding(db, series_id=s4.id, physician="dr", measurements={}, code="CXR-200")

    records, report = site_manifest(db)
    by_id = {r["image_id"]: r for r in records}
    assert set(by_id) == {"s1", "s2"}
    assert report["skipped_unlabeled"] == 1 and report["skipped_no_age"] == 1
    l1 = by_id["s1"]["labels"]
    assert (l1["CXR-200"], l1["CXR-104"], l1["CXR-500"]) == (1, 1, 0)
    assert "CXR-201" not in l1                     # не подписано — молчание маскируется
    l2 = by_id["s2"]["labels"]
    assert l2["CXR-000"] == 1 and l2["CXR-200"] == 0 and "CXR-108" not in l2   # 108 — только КТ
    assert by_id["s1"]["population"] == "pediatric" and by_id["s1"]["split"] in ("train", "validate", "test")


def test_shadow_report_against_signed_reports(db):
    mv = _model(db, status=ModelStatus.SHADOW)
    agree, disagree, unsigned = _series(db, uid="a"), _series(db, uid="b", manufacturer="GE"), _series(db, uid="c")
    for s in (agree, disagree, unsigned):
        classification.classify_series(db, series=s, model_version=mv, model=FixedModel(PROBS))  # черновик CXR-200
    corrections.create_physician_finding(db, series_id=agree.id, physician="dr", measurements={}, code="CXR-200")
    corrections.create_physician_finding(db, series_id=disagree.id, physician="dr", measurements={}, code="CXR-104")
    _finalize(db, agree)
    _finalize(db, disagree)

    rep = shadow_report(db, mv.id)
    assert rep["shadow_runs"] == 3 and rep["reviewed_cases"] == 2
    assert rep["per_code"]["CXR-200"] == {"tp": 1, "fp": 1, "fn": 0, "tn": 0, "sensitivity": 1.0, "ppv": 0.5}
    assert rep["disagreement_rate"] == 0.5 and rep["miss_rate"] == 0.5    # CXR-104 пропущена
    assert rep["per_manufacturer"]["GE"]["disagreement_rate"] == 1.0


def test_report_sentence_for_qualitative_finding():
    draft = build_draft([FindingInput("f1", "Плевральный выпот", "CXR-200", "MEDVIZ-CXR",
                                      {"confidence": 0.8}, True)])
    assert draft.text == "Плевральный выпот [MEDVIZ-CXR:CXR-200]."
