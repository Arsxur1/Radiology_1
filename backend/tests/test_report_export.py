"""Тесты HTML-выгрузки заключения (ТЗ, FR-8)."""

from app.services.report_export import ReportExportInput, render_html


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


def test_html_contains_findings_and_trace():
    out = render_html(_data())
    assert "Сердце" in out
    assert 'data-finding-id="f1"' in out  # трассировка предложения к находке
    assert "dr.ivanov" in out


def test_html_escapes_content():
    out = render_html(_data(finalized_by="<script>x</script>"))
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;" in out


def test_html_localized_uz():
    out = render_html(_data(language="uz"))
    assert "Xulosa" in out
