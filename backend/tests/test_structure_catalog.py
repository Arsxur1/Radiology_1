"""Тесты каталога структур и определения области (этап 2, расширение)."""

from app.services.structure_catalog import (
    region_from_protocol,
    structure_by_key,
    structures_for_region,
)


def test_regions_have_structures():
    assert len(structures_for_region("CHEST")) > 0
    assert len(structures_for_region("ABDOMEN")) > 0
    assert len(structures_for_region("BRAIN")) > 0
    assert structures_for_region("UNKNOWN") == ()
    assert structures_for_region(None) == ()


def test_structure_lookup_across_regions():
    assert structure_by_key("liver").label_ru == "Печень"
    assert structure_by_key("brain").label_ru == "Головной мозг"
    assert structure_by_key("heart").label_ru == "Сердце"
    assert structure_by_key("nonexistent") is None


def test_region_from_protocol_en():
    assert region_from_protocol("Chest CT") == "CHEST"
    assert region_from_protocol("Abdomen with contrast") == "ABDOMEN"
    assert region_from_protocol("Brain MRI") == "BRAIN"
    assert region_from_protocol("Head") == "HEAD"


def test_region_from_protocol_ru():
    assert region_from_protocol("КТ грудной клетки") == "CHEST"
    assert region_from_protocol("КТ брюшной полости") == "ABDOMEN"
    assert region_from_protocol("МРТ головного мозга") == "BRAIN"
    assert region_from_protocol("Рентгенография легких") == "CHEST"
    assert region_from_protocol(None, "Обзорная рентгенограмма лёгких") == "CHEST"


def test_region_from_protocol_uz():
    assert region_from_protocol("Ko'krak qafasi rentgenografiyasi") == "CHEST"
    assert region_from_protocol("Ko‘krak qafasi") == "CHEST"
    assert region_from_protocol("Кўкрак қафаси рентгени") == "CHEST"
    assert region_from_protocol(None, "O'pka KT") == "CHEST"
    assert region_from_protocol("Qorin bo'shlig'i KT") == "ABDOMEN"


def test_region_from_description_fallback():
    assert region_from_protocol(None, "abdomen axial") == "ABDOMEN"


def test_region_unknown_returns_none():
    assert region_from_protocol("Wrist X-ray") is None
    assert region_from_protocol(None, None) is None


def test_region_prefers_dicom_body_part():
    from app.services.structure_catalog import region_for_study

    assert region_for_study("CHEST", None, "неизвестно") == "CHEST"
    assert region_for_study("Грудная клетка", None, None) == "CHEST"
    assert region_for_study("XYZ", "Chest PA", None) == "CHEST"        # запасной путь — протокол
    assert region_for_study(None, None, "Рентгенография ОГК") == "CHEST"
    assert region_for_study(None, None, None) is None
