"""Тесты черновика заключения (ТЗ, FR-8): только подтверждённые, трассируемость."""

import pytest

from app.services.report_draft import (
    FindingInput,
    UnconfirmedFindingError,
    build_draft,
)


def _f(fid, code, label, vol, confirmed=True):
    return FindingInput(
        finding_id=fid, label=label, code=code, coding_system="RadLex",
        measurements={"volume_ml": vol}, confirmed=confirmed,
    )


def test_draft_from_confirmed_only():
    draft = build_draft([_f("f1", "RID1385", "Сердце", 320.0)])
    assert "Сердце" in draft.text
    assert "320" in draft.text
    assert "мл" in draft.text


def test_refuses_unconfirmed_finding():
    # FR-8: неподтверждённая находка не может попасть в черновик.
    with pytest.raises(UnconfirmedFindingError):
        build_draft([_f("f1", "RID1385", "Сердце", 320.0, confirmed=False)])


def test_every_sentence_traces_to_finding():
    # Трассируемость: каждое предложение → конкретная находка (FR-8).
    findings = [_f("f1", "RID1385", "Сердце", 320.0), _f("f2", "RID480", "Аорта", 90.0)]
    draft = build_draft(findings)
    assert len(draft.sentences) == 2
    mapped_ids = set(draft.sentence_map.values())
    assert mapped_ids == {"f1", "f2"}


def test_deterministic_order():
    a = build_draft([_f("f2", "RID480", "Аорта", 90.0), _f("f1", "RID1385", "Сердце", 320.0)])
    b = build_draft([_f("f1", "RID1385", "Сердце", 320.0), _f("f2", "RID480", "Аорта", 90.0)])
    assert a.text == b.text  # порядок входа не влияет


def test_language_uzbek_units():
    draft = build_draft([_f("f1", "RID1385", "Yurak", 320.0)], language="uz")
    assert "hajm" in draft.text


def test_no_measurements_sentence():
    f = FindingInput("f1", "Структура", "RID1", "RadLex", {}, confirmed=True)
    draft = build_draft([f])
    assert "измерения отсутствуют" in draft.text
