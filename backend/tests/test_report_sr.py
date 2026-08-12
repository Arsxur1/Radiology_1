"""Тесты дерева содержания DICOM SR (ТЗ, FR-8): трассируемость до находок."""

from app.services.report_export import ReportExportInput
from app.services.report_sr import (
    VT_CONTAINER,
    VT_TEXT,
    build_sr_content,
    sr_traceability_map,
)


def _data(**over):
    base = dict(
        study_uid="1.2.3", language="ru",
        draft_text="Сердце — объём 320 мл. Аорта — объём 90 мл.",
        sentence_map={"0": "f1", "1": "f2"},
        finalized_by="dr.ivanov",
        sentences=["Сердце — объём 320 мл.", "Аорта — объём 90 мл."],
    )
    base.update(over)
    return ReportExportInput(**base)


def test_sr_root_is_container():
    root = build_sr_content(_data())
    assert root.value_type == VT_CONTAINER
    assert len(root.children) == 2
    assert all(c.value_type == VT_TEXT for c in root.children)


def test_sr_items_carry_text_and_finding():
    root = build_sr_content(_data())
    first = root.children[0]
    assert first.text == "Сердце — объём 320 мл."
    assert first.finding_id == "f1"


def test_sr_traceability_map():
    root = build_sr_content(_data())
    # Каждый пункт SR трассируется до конкретной находки (FR-8).
    assert sr_traceability_map(root) == {"0": "f1", "1": "f2"}


def test_sr_empty_report():
    root = build_sr_content(_data(sentences=[], sentence_map={}))
    assert root.children == []
    assert sr_traceability_map(root) == {}
