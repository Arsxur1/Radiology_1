"""Тесты совмещения модальностей (ТЗ, FR-4)."""

from __future__ import annotations

import pytest

from app.models.imaging import Series, Study
from app.models.patient import Patient
from app.models.registration import RegistrationReview, RegistrationStage
from app.services import registration
from app.services.registration import (
    STAGE_ORDER,
    RegistrationError,
    StubRegistrationEngine,
    ensure_usable_for_measurements,
    run_registration,
)


def _two_series(db, *, same_patient=True):
    p1 = Patient()
    db.add(p1)
    db.flush()
    p2 = p1 if same_patient else Patient()
    if not same_patient:
        db.add(p2)
        db.flush()

    st1 = Study(patient_id=p1.id, study_instance_uid="ct", modality="CT")
    st2 = Study(patient_id=p2.id, study_instance_uid="mr", modality="MR")
    db.add_all([st1, st2])
    db.flush()
    se1 = Series(study_id=st1.id, series_instance_uid="ct-s", modality="CT", object_prefix="ct/x")
    se2 = Series(study_id=st2.id, series_instance_uid="mr-s", modality="MR", object_prefix="mr/x")
    db.add_all([se1, se2])
    db.flush()
    return se1, se2


def test_stage_order_is_rigid_affine_deformable():
    assert STAGE_ORDER == [
        RegistrationStage.RIGID, RegistrationStage.AFFINE, RegistrationStage.DEFORMABLE
    ]


def test_registration_runs_pending_by_default(db):
    fixed, moving = _two_series(db)
    reg = run_registration(
        db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine()
    )
    # Метрика — mutual information; результат не подтверждён и негоден для измерений.
    assert reg.metric_name == "mutual_information"
    assert reg.metric_value is not None
    assert reg.review_status == RegistrationReview.PENDING
    assert reg.usable_for_measurements() is False


def test_unapproved_registration_blocks_measurements(db):
    fixed, moving = _two_series(db)
    reg = run_registration(
        db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine()
    )
    with pytest.raises(RegistrationError):
        ensure_usable_for_measurements(reg)


def test_approved_registration_usable(db):
    fixed, moving = _two_series(db)
    reg = run_registration(
        db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine()
    )
    registration.review_registration(
        db, registration_id=reg.id, approved=True, physician="dr"
    )
    assert reg.usable_for_measurements() is True
    ensure_usable_for_measurements(reg)  # не бросает


def test_rejected_registration_still_blocked(db):
    fixed, moving = _two_series(db)
    reg = run_registration(
        db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine()
    )
    registration.review_registration(db, registration_id=reg.id, approved=False, physician="dr")
    assert reg.usable_for_measurements() is False


def test_cannot_register_different_patients(db):
    fixed, moving = _two_series(db, same_patient=False)
    with pytest.raises(RegistrationError, match="разным пациентам"):
        run_registration(
            db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine()
        )


def test_deterministic_metric(db):
    fixed, moving = _two_series(db)
    engine = StubRegistrationEngine()
    a = engine.register("ct/x", "mr/x", RegistrationStage.DEFORMABLE)
    b = engine.register("ct/x", "mr/x", RegistrationStage.DEFORMABLE)
    assert a.metric_value == b.metric_value
    # Более поздняя стадия даёт не меньшую метрику.
    rigid = engine.register("ct/x", "mr/x", RegistrationStage.RIGID)
    assert a.metric_value >= rigid.metric_value
