"""Тесты плана обезличивания (ТЗ, SR-9). Без зависимости от самого DICOM-ввода."""

from types import SimpleNamespace

from app.services.anonymization import _derive_patient_pseudonym, _derive_uid, build_deid_plan


class FakeDataset(SimpleNamespace):
    """Имитация pydicom.Dataset: hasattr/getattr достаточно для build_deid_plan."""


def test_uid_derivation_deterministic():
    # Повторный приём того же UID даёт тот же псевдоним (идемпотентность).
    uid = "1.2.3.4.5.6"
    assert _derive_uid(uid) == _derive_uid(uid)
    assert _derive_uid(uid) != _derive_uid("1.2.3.4.5.7")


def test_patient_pseudonym_deterministic():
    a = _derive_patient_pseudonym("MRN-42", "clinic-1")
    b = _derive_patient_pseudonym("MRN-42", "clinic-1")
    c = _derive_patient_pseudonym("MRN-43", "clinic-1")
    assert a == b
    assert a != c


def test_plan_captures_phi_and_removes_tags():
    ds = FakeDataset(
        PatientName="Иванов Пётр",
        PatientID="MRN-42",
        IssuerOfPatientID="clinic-1",
        StudyInstanceUID="1.2.3.4.5.6",
        AccessionNumber="ACC-1",
        PatientBirthTime="120000",
        StudyID="STU-9",
        DeviceSerialNumber="SN-777",
        Modality="CT",
    )
    plan = build_deid_plan(ds)
    assert plan.real_mrn == "MRN-42"
    assert plan.real_name == "Иванов Пётр"
    assert plan.pseudonym_study_uid == _derive_uid("1.2.3.4.5.6")
    # PHI-теги помечены к удалению (в т.ч. расширенный набор SR-9).
    assert "PatientName" in plan.removed_tags
    assert "PatientID" in plan.removed_tags
    assert "AccessionNumber" in plan.removed_tags
    assert "PatientBirthTime" in plan.removed_tags
    assert "StudyID" in plan.removed_tags
    assert "DeviceSerialNumber" in plan.removed_tags
    # Клинически значимый тег (модальность) НЕ в списке на удаление.
    assert "Modality" not in plan.removed_tags
