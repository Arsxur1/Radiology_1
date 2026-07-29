"""Тесты сравнения во времени (ТЗ, FR-7). Детерминированно, без ИИ."""

from datetime import datetime

from app.services.temporal import FindingPoint, build_series


def _p(date, fid, code, vol):
    return FindingPoint(
        study_id=f"st-{fid}", study_date=date, finding_id=fid,
        code=code, structure_key="heart", measurements={"volume_ml": vol},
    )


def test_series_grouped_by_code_and_ordered():
    points = [
        _p(datetime(2026, 3, 1), "f2", "RID1385", 320.0),
        _p(datetime(2026, 1, 1), "f1", "RID1385", 300.0),
    ]
    series = build_series(points)
    assert len(series) == 1
    s = series[0]
    # Отсортировано по времени: сначала январь, потом март.
    assert [p.finding_id for p in s.points] == ["f1", "f2"]


def test_delta_growth():
    points = [
        _p(datetime(2026, 1, 1), "f1", "RID1385", 300.0),
        _p(datetime(2026, 3, 1), "f2", "RID1385", 330.0),
    ]
    s = build_series(points)[0]
    d = s.deltas["volume_ml"]
    assert d.absolute == 30.0
    assert d.percent == 10.0
    assert d.direction == "рост"


def test_delta_decrease():
    points = [
        _p(datetime(2026, 1, 1), "f1", "RID1385", 400.0),
        _p(datetime(2026, 3, 1), "f2", "RID1385", 300.0),
    ]
    d = build_series(points)[0].deltas["volume_ml"]
    assert d.direction == "снижение"
    assert d.absolute == -100.0


def test_single_point_no_delta():
    s = build_series([_p(datetime(2026, 1, 1), "f1", "RID1385", 300.0)])[0]
    assert s.deltas == {}


def test_different_structures_separate_series():
    points = [
        FindingPoint("st1", datetime(2026, 1, 1), "f1", "RID1385", "heart", {"volume_ml": 300.0}),
        FindingPoint("st1", datetime(2026, 1, 1), "f2", "RID480", "aorta", {"volume_ml": 90.0}),
    ]
    series = build_series(points)
    assert len(series) == 2
