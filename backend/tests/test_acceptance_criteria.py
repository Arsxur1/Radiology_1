"""Автоматизированная проверка критериев приёмки (ТЗ, раздел 10).

Каждый тест соответствует пункту раздела 10. Прогоняются на реальной БД (SQLite
через переносимые типы; на PostgreSQL действуют дополнительно триггер и права).
"""

from __future__ import annotations

from datetime import datetime

from app.models.audit import AuditAction
from app.models.imaging import Series, Study
from app.models.ml import ModelStatus, ModelVersion
from app.models.patient import Patient
from app.services import audit, corrections, segmentation
from app.services.anonymization import build_deid_plan
from app.services.inference_adapters import StubSegmentationModel
from app.services.measurements import VoxelSpacing, volume_ml

APPLIC = {
    "modality": ["CT"], "body_part": ["CHEST"], "slice_thickness_mm": {"max": 3.0},
    "age": {"min_years": 18}, "manufacturers": ["Siemens"], "allow_lossy": False,
}


def _series(db):
    p = Patient()
    db.add(p)
    db.flush()
    st = Study(patient_id=p.id, study_instance_uid="s1", modality="CT",
               study_date=datetime(2026, 1, 1), manufacturer="Siemens", protocol="Chest CT")
    db.add(st)
    db.flush()
    se = Series(study_id=st.id, series_instance_uid="se1", modality="CT",
                slice_thickness_mm=1.0, voxel_spacing=[0.7, 0.7, 1.0], object_prefix="p/x")
    db.add(se)
    db.flush()
    return p, st, se


# ─── Критерий: полная трассируемость ──────────────────────────────────────────
def test_traceability_inference_and_findings(db):
    _, _, se = _series(db)
    mv = ModelVersion(name="m", semver="1.0.0", weights_hash="hash-x",
                      applicability=APPLIC, status=ModelStatus.ACTIVE)
    db.add(mv)
    db.flush()
    outcome = segmentation.segment_series(
        db, series=se, model_version=mv,
        model=StubSegmentationModel(["heart"], weights_hash="hash-x"), age_years=40.0,
    )
    from app.models.ml import Finding, InferenceResult

    inf = db.get(InferenceResult, outcome.inference_result_id)
    # Восстановимы: версия модели, входная серия, параметры препроцессинга (SR-5).
    assert inf.model_version_id == mv.id
    assert inf.series_id == se.id
    assert "adapter" in inf.preprocessing_params
    f = db.query(Finding).first()
    assert f.inference_result_id == inf.id


# ─── Критерий: воспроизводимость ──────────────────────────────────────────────
def test_reproducibility_measurements():
    spacing = VoxelSpacing(0.7, 0.7, 1.5)
    assert volume_ml(123456, spacing) == volume_ml(123456, spacing)


def test_reproducibility_deidentification():
    class DS(dict):
        def __getattr__(self, k):
            return self.get(k)

        def __setattr__(self, k, v):
            self[k] = v

        def __delattr__(self, k):
            self.pop(k, None)

        def copy(self):
            return DS(self)

    ds = DS(PatientID="MRN-1", StudyInstanceUID="1.2.3", PatientName="X")
    a = build_deid_plan(ds)
    b = build_deid_plan(ds)
    assert a.pseudonym_patient_id == b.pseudonym_patient_id
    assert a.pseudonym_study_uid == b.pseudonym_study_uid


# ─── Критерий: отказ вне границ применимости, а не результат ──────────────────
def test_refusal_out_of_range(db):
    import pytest

    _, _, se = _series(db)
    mv = ModelVersion(name="m", semver="1.0.0", weights_hash="h",
                      applicability=APPLIC, status=ModelStatus.ACTIVE)
    db.add(mv)
    db.flush()
    with pytest.raises(segmentation.ApplicabilityRefused):
        segmentation.segment_series(
            db, series=se, model_version=mv,
            model=StubSegmentationModel(["heart"]), age_years=5.0,  # педиатрия
        )


# ─── Критерий: целостность аудит-лога (хеш-цепочка) ───────────────────────────
def test_audit_chain_intact(db):
    audit.record(db, actor="a", action=AuditAction.PATIENT_ACCESS)
    audit.record(db, actor="b", action=AuditAction.EXPORT)
    db.flush()
    assert audit.verify_chain(db) is True


def test_audit_chain_detects_tampering(db):
    e1 = audit.record(db, actor="a", action=AuditAction.PATIENT_ACCESS)
    audit.record(db, actor="b", action=AuditAction.EXPORT)
    db.flush()
    # Подмена содержимого прошлой записи ломает цепочку (обнаружение подмены).
    e1.actor = "attacker"
    db.flush()
    assert audit.verify_chain(db) is False


# ─── Критерий: правки фиксируются как обучающий сигнал ────────────────────────
def test_corrections_recorded_as_training_signal(db):
    _, _, se = _series(db)
    mv = ModelVersion(name="m", semver="1.0.0", weights_hash="h",
                      applicability=APPLIC, status=ModelStatus.ACTIVE)
    db.add(mv)
    db.flush()
    outcome = segmentation.segment_series(
        db, series=se, model_version=mv,
        model=StubSegmentationModel(["heart"]), age_years=40.0,
    )
    from app.models.ml import Correction

    corrections.reject_finding(db, finding_id=outcome.finding_ids[0], physician="dr", reason="ложное")
    c = db.query(Correction).one()
    assert c.author == "dr"
    assert c.before is not None  # сохранён снимок «было»
