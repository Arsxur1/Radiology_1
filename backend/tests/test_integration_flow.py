"""Сквозной интеграционный тест ключевого пути платформы.

Пациент → исследование → серия → активная модель → сегментация → находки →
правки врача → сравнение во времени → черновик заключения. Проверяет, что
контур работает целиком и инварианты безопасности соблюдаются на реальной БД.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models.imaging import Series, Study
from app.models.ml import (
    ConfirmationStatus,
    CorrectionType,
    FindingSource,
    ModelStatus,
    ModelVersion,
)
from app.models.patient import Patient
from app.services import corrections, report_repo, segmentation, temporal_repo
from app.services.inference_adapters import StubSegmentationModel
from app.services.report_draft import UnconfirmedFindingError
from app.services.segmentation import ApplicabilityRefused
from app.services.structure_catalog import structures_for_region

CHEST_APPLICABILITY = {
    "modality": ["CT"],
    "body_part": ["CHEST"],
    "slice_thickness_mm": {"max": 3.0},
    "age": {"min_years": 18},
    "manufacturers": ["Siemens"],
    "allow_lossy": False,
}


def _make_series(db, *, thickness=1.0, manufacturer="Siemens", lossy=False, protocol="Chest CT"):
    patient = Patient()
    db.add(patient)
    db.flush()
    study = Study(
        patient_id=patient.id,
        study_instance_uid=f"study-{patient.id.hex[:8]}",
        modality="CT",
        study_date=datetime(2026, 1, 1),
        manufacturer=manufacturer,
        protocol=protocol,
    )
    db.add(study)
    db.flush()
    series = Series(
        study_id=study.id,
        series_instance_uid=f"series-{patient.id.hex[:8]}",
        modality="CT",
        slice_thickness_mm=thickness,
        voxel_spacing=[0.7, 0.7, thickness],
        lossy_compressed=lossy,
        object_prefix="prefix/x",
    )
    db.add(series)
    db.flush()
    return patient, study, series


def _model(db):
    mv = ModelVersion(
        name="chest", semver="1.0.0", weights_hash="abc",
        applicability=CHEST_APPLICABILITY, status=ModelStatus.ACTIVE,
    )
    db.add(mv)
    db.flush()
    return mv


def test_full_flow_segment_correct_report(db):
    patient, study, series = _make_series(db)
    mv = _model(db)
    keys = [s.key for s in structures_for_region("CHEST")]
    model = StubSegmentationModel(keys, weights_hash=mv.weights_hash)

    # Сегментация → находки (source=model, PENDING).
    outcome = segmentation.segment_series(
        db, series=series, model_version=mv, model=model, age_years=45.0
    )
    assert outcome.structure_count == len(keys)

    from app.models.ml import Finding

    findings = db.query(Finding).all()
    assert all(f.source == FindingSource.MODEL for f in findings)
    assert all(f.confirmation_status == ConfirmationStatus.PENDING for f in findings)

    # Черновик до подтверждения невозможен (FR-8): нет подтверждённых находок → пусто.
    report = report_repo.generate_report_draft(db, study_id=study.id)
    assert report.draft_text == ""

    # Врач подтверждает одну находку и правит другую (FR-9).
    corrections.confirm_finding(db, finding_id=findings[0].id, physician="dr", time_spent_seconds=12)
    corrections.modify_finding(
        db, finding_id=findings[1].id, physician="dr",
        new_measurements={"volume_ml": 999.0}, time_spent_seconds=30,
    )

    # Каждая правка породила correction (обучающий сигнал).
    from app.models.ml import Correction

    ctypes = {c.correction_type for c in db.query(Correction).all()}
    assert CorrectionType.ACCEPTED in ctypes
    assert CorrectionType.MODIFIED in ctypes

    # Теперь черновик собирается из подтверждённых находок и трассируется.
    report = report_repo.generate_report_draft(db, study_id=study.id)
    assert report.draft_text
    assert len(report.sentence_map) == 2  # две подтверждённые находки

    # Финализация — активное действие врача.
    report = report_repo.finalize_report(db, report_id=report.id, physician="dr")
    assert report.finalized_by == "dr"


def test_flow_refuses_out_of_range(db):
    # Педиатрия для взрослой модели — отказ по SR-7, находки не создаются.
    _, _, series = _make_series(db)
    mv = _model(db)
    model = StubSegmentationModel(["heart"], weights_hash=mv.weights_hash)
    with pytest.raises(ApplicabilityRefused):
        segmentation.segment_series(db, series=series, model_version=mv, model=model, age_years=6.0)

    from app.models.ml import Finding

    assert db.query(Finding).count() == 0


def test_flow_temporal_dynamics(db):
    # Две даты одного пациента → динамика подтверждённой структуры (FR-7).
    patient, study1, series1 = _make_series(db)
    mv = _model(db)
    model = StubSegmentationModel(["heart"], weights_hash=mv.weights_hash)

    from app.models.ml import Finding

    segmentation.segment_series(db, series=series1, model_version=mv, model=model, age_years=45.0)
    f1 = db.query(Finding).one()
    corrections.modify_finding(
        db, finding_id=f1.id, physician="dr", new_measurements={"volume_ml": 300.0}
    )

    # Второе исследование того же пациента.
    study2 = Study(
        patient_id=patient.id, study_instance_uid="study-2", modality="CT",
        study_date=datetime(2026, 6, 1), manufacturer="Siemens", protocol="Chest CT",
    )
    db.add(study2)
    db.flush()
    series2 = Series(
        study_id=study2.id, series_instance_uid="series-2", modality="CT",
        slice_thickness_mm=1.0, voxel_spacing=[0.7, 0.7, 1.0], object_prefix="prefix/y",
    )
    db.add(series2)
    db.flush()
    segmentation.segment_series(db, series=series2, model_version=mv, model=model, age_years=45.0)
    f2 = db.query(Finding).filter(Finding.series_id == series2.id).one()
    corrections.modify_finding(
        db, finding_id=f2.id, physician="dr", new_measurements={"volume_ml": 330.0}
    )

    series = temporal_repo.patient_series(db, patient_id=patient.id)
    assert len(series) == 1
    delta = series[0].deltas["volume_ml"]
    assert delta.current == 330.0
    assert delta.previous == 300.0
    assert delta.direction == "рост"


def test_age_from_study_passes_gate(db):
    # Возраст из исследования (без явной передачи) проходит взрослый гейт (SR-7).
    _, study, series = _make_series(db)
    study.patient_age_years = 45.0
    db.flush()
    mv = _model(db)
    model = StubSegmentationModel(["heart"], weights_hash=mv.weights_hash)
    outcome = segmentation.segment_series(db, series=series, model_version=mv, model=model)
    assert outcome.structure_count == 1


def test_age_from_study_pediatric_refused(db):
    # Младенец в исследовании → отказ взрослой модели даже без явной передачи возраста.
    _, study, series = _make_series(db)
    study.patient_age_years = 1.5
    db.flush()
    mv = _model(db)
    model = StubSegmentationModel(["heart"], weights_hash=mv.weights_hash)
    with pytest.raises(ApplicabilityRefused):
        segmentation.segment_series(db, series=series, model_version=mv, model=model)


def test_abdomen_region_flow(db):
    # Область определяется по протоколу «брюшной полости»; создаются её структуры.
    from app.models.imaging import Series, Study
    from app.models.ml import Finding
    from app.models.patient import Patient
    from app.services.structure_catalog import structures_for_region

    patient = Patient()
    db.add(patient)
    db.flush()
    study = Study(
        patient_id=patient.id, study_instance_uid="ab-1", modality="CT",
        manufacturer="Siemens", protocol="КТ брюшной полости", patient_age_years=50.0,
    )
    db.add(study)
    db.flush()
    series = Series(
        study_id=study.id, series_instance_uid="ab-1-s", modality="CT",
        slice_thickness_mm=1.0, voxel_spacing=[0.7, 0.7, 1.0], object_prefix="ab/1",
    )
    db.add(series)
    db.flush()

    abdomen_applic = {**CHEST_APPLICABILITY, "body_part": ["ABDOMEN"]}
    mv = ModelVersion(name="abd", semver="1.0.0", weights_hash="h",
                      applicability=abdomen_applic, status=ModelStatus.ACTIVE)
    db.add(mv)
    db.flush()
    keys = [s.key for s in structures_for_region("ABDOMEN")]
    model = StubSegmentationModel(keys, weights_hash="h")

    outcome = segmentation.segment_series(db, series=series, model_version=mv, model=model)
    assert outcome.structure_count == len(keys)
    labels = {f.label for f in db.query(Finding).all()}
    assert "Печень" in labels


def test_report_rejects_unconfirmed_via_service(db):
    # Прямая сборка из неподтверждённой находки запрещена (FR-8).
    from app.services.report_draft import FindingInput, build_draft

    with pytest.raises(UnconfirmedFindingError):
        build_draft([FindingInput("f1", "Сердце", "RID1385", "RadLex", {"volume_ml": 1.0}, False)])
