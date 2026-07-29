"""Тесты гейта границ применимости (ТЗ, SR-7)."""

from app.services.applicability import SeriesContext, check_applicability

CHEST_CT = {
    "modality": ["CT"],
    "body_part": ["CHEST", "THORAX"],
    "slice_thickness_mm": {"max": 3.0},
    "age": {"min_years": 18},
    "manufacturers": ["Siemens", "GE", "Philips", "Canon"],
    "allow_lossy": False,
    "require_contrast": None,
}


def _ctx(**over):
    base = dict(
        modality="CT", body_part="CHEST", slice_thickness_mm=1.0,
        manufacturer="Siemens", lossy_compressed=False, contrast_agent=None,
        patient_age_years=40.0,
    )
    base.update(over)
    return SeriesContext(**base)


def test_admits_valid_series():
    d = check_applicability(_ctx(), CHEST_CT)
    assert d.admitted is True
    assert d.reasons == []


def test_refuses_pediatric():
    # Модель для взрослых обязана отказать в педиатрическом исследовании (п.1.2, SR-7).
    d = check_applicability(_ctx(patient_age_years=8.0), CHEST_CT)
    assert d.admitted is False
    assert any("Возраст" in r for r in d.reasons)


def test_refuses_thick_slices():
    d = check_applicability(_ctx(slice_thickness_mm=5.0), CHEST_CT)
    assert d.admitted is False
    assert any("Толщина среза" in r for r in d.reasons)


def test_refuses_wrong_modality():
    d = check_applicability(_ctx(modality="MR"), CHEST_CT)
    assert d.admitted is False


def test_refuses_unknown_manufacturer():
    d = check_applicability(_ctx(manufacturer="NoName"), CHEST_CT)
    assert d.admitted is False
    assert any("Аппарат" in r for r in d.reasons)


def test_refuses_lossy():
    d = check_applicability(_ctx(lossy_compressed=True), CHEST_CT)
    assert d.admitted is False


def test_missing_age_refused_when_required():
    # Отсутствие возраста при наличии возрастной границы — отказ, а не пропуск.
    d = check_applicability(_ctx(patient_age_years=None), CHEST_CT)
    assert d.admitted is False


def test_reports_all_violations():
    d = check_applicability(
        _ctx(modality="MR", slice_thickness_mm=5.0, patient_age_years=5.0), CHEST_CT
    )
    assert d.admitted is False
    assert len(d.reasons) >= 3
