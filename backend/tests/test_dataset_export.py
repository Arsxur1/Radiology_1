"""Тесты сборки выборки экспорта (ТЗ, FR-9): фильтры отражаются в SQL."""

from app.models.ml import CorrectionType
from app.services.dataset_export import ExportFilters, build_query


def test_default_filters_include_all_correction_types():
    f = ExportFilters()
    assert set(f.correction_types) == set(CorrectionType)


def test_modality_filter_present_in_query():
    sql = str(build_query(ExportFilters(modality="CT")))
    assert "series.modality" in sql


def test_manufacturer_filter_present_in_query():
    sql = str(build_query(ExportFilters(manufacturer="Siemens")))
    assert "study.manufacturer" in sql


def test_min_time_filter_present_in_query():
    sql = str(build_query(ExportFilters(min_time_spent_seconds=5.0)))
    assert "time_spent_seconds" in sql
