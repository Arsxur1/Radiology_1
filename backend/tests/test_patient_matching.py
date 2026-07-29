"""Тесты нормализации идентификаторов (ТЗ, FR-1: транслитерация кириллица/латиница)."""

from app.services.patient_matching import normalize_identifier


def test_cyrillic_latin_equivalence():
    # Кириллическое и транслитерированное написание сводятся к одному ключу.
    assert normalize_identifier("Иванов Пётр") == normalize_identifier("ivanov petr")


def test_uzbek_cyrillic():
    # Узбекская кириллица (ў, қ, ғ, ҳ) транслитерируется.
    assert normalize_identifier("Ғафуров") == normalize_identifier("gafurov")


def test_whitespace_and_case():
    assert normalize_identifier("  ПЕТРОВ   ИВАН ") == "petrov ivan"
