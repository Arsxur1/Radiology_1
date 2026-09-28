"""Тесты словаря находок ОГК (ТЗ, FR-9). Разметка врачом, не авто-диагноз."""

from app.services.finding_vocabulary import (
    CHEST_FINDINGS,
    by_code,
    groups,
    list_findings,
)


def test_codes_unique():
    codes = [f.code for f in CHEST_FINDINGS]
    assert len(codes) == len(set(codes))


def test_filter_by_modality():
    ct_only = [f for f in list_findings(modality="CT")]
    assert any(f.code == "CXR-108" for f in ct_only)  # матовое стекло — только КТ
    cr = list_findings(modality="CR")
    assert all("CR" in f.modalities for f in cr)
    assert not any(f.code == "CXR-108" for f in cr)  # не показывается для рентгена


def test_filter_by_group():
    pleura = list_findings(group="плевра")
    labels = {f.label_ru for f in pleura}
    assert "Пневмоторакс" in labels
    assert "Плевральный выпот" in labels


def test_groups_listed_in_order():
    g = groups()
    assert g[0] == "норма"
    assert "лёгкие" in g
    assert "устройства" in g


def test_by_code():
    assert by_code("CXR-200").label_ru == "Плевральный выпот"
    assert by_code("CXR-500").group == "сердце"
    assert by_code("NONE") is None


def test_normal_present():
    assert by_code("CXR-000").label_ru == "Без патологических изменений"
