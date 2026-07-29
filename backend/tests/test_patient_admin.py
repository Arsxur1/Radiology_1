"""Тесты объединения/разъединения пациентов (ТЗ, FR-1)."""

from __future__ import annotations

import pytest

from app.models.imaging import Study
from app.models.patient import Patient, PatientIdentifier
from app.services import patient_admin
from app.services.patient_admin import MergeError


def _patient(db, *, mrn: str) -> Patient:
    p = Patient()
    db.add(p)
    db.flush()
    db.add(PatientIdentifier(patient_id=p.id, id_type="mrn", normalized_value=mrn))
    db.flush()
    return p


def _study(db, patient, uid: str) -> Study:
    st = Study(patient_id=patient.id, study_instance_uid=uid, modality="CT")
    db.add(st)
    db.flush()
    return st


def test_merge_moves_studies_and_identifiers(db):
    # Один человек под двумя написаниями (кириллица/латиница).
    a = _patient(db, mrn="ivanov petr")     # латиница
    b = _patient(db, mrn="ivanov petr cyr")  # другое написание
    _study(db, a, "s-a")
    _study(db, b, "s-b")

    outcome = patient_admin.merge_patients(db, source_id=a.id, target_id=b.id, actor="dr")
    assert outcome.moved_studies == 1
    assert outcome.moved_identifiers == 1

    db.refresh(a)
    assert a.is_merged is True
    assert a.merged_into_id == b.id
    # Все исследования теперь у b.
    b_studies = db.query(Study).filter(Study.patient_id == b.id).count()
    assert b_studies == 2


def test_cannot_merge_into_self(db):
    a = _patient(db, mrn="x")
    with pytest.raises(MergeError):
        patient_admin.merge_patients(db, source_id=a.id, target_id=a.id, actor="dr")


def test_cannot_merge_already_merged_source(db):
    a = _patient(db, mrn="a")
    b = _patient(db, mrn="b")
    c = _patient(db, mrn="c")
    patient_admin.merge_patients(db, source_id=a.id, target_id=b.id, actor="dr")
    with pytest.raises(MergeError):
        patient_admin.merge_patients(db, source_id=a.id, target_id=c.id, actor="dr")


def test_split_extracts_new_patient(db):
    # Две персоны ошибочно объединены — разъединяем.
    a = _patient(db, mrn="person-1")
    b = _patient(db, mrn="person-2")
    st_b = _study(db, b, "s-b")
    patient_admin.merge_patients(db, source_id=b.id, target_id=a.id, actor="dr")

    # Идентификатор person-2 теперь у a; выделяем его обратно с исследованием.
    ident_b = db.query(PatientIdentifier).filter(
        PatientIdentifier.normalized_value == "person-2"
    ).one()

    outcome = patient_admin.split_patient(
        db, source_patient_id=a.id,
        identifier_ids=[ident_b.id], study_ids=[st_b.id], actor="dr",
    )
    assert outcome.moved_identifiers == 1
    assert outcome.moved_studies == 1

    db.refresh(ident_b)
    assert ident_b.patient_id == outcome.new_patient_id
    assert ident_b.merged_into is None
    assert db.get(Study, st_b.id).patient_id == outcome.new_patient_id


def test_split_rejects_foreign_identifier(db):
    a = _patient(db, mrn="a")
    _patient(db, mrn="b")  # отдельная персона, не связана с a
    ident_b = db.query(PatientIdentifier).filter(
        PatientIdentifier.normalized_value == "b"
    ).one()
    # Идентификатор b не принадлежит a → ошибка.
    with pytest.raises(MergeError):
        patient_admin.split_patient(
            db, source_patient_id=a.id, identifier_ids=[ident_b.id], actor="dr"
        )


def test_split_requires_something(db):
    a = _patient(db, mrn="a")
    with pytest.raises(MergeError):
        patient_admin.split_patient(db, source_patient_id=a.id, identifier_ids=[], actor="dr")
