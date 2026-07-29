"""Тесты расчёта доли отклонений (ТЗ, FR-11)."""

from app.models.ml import CorrectionType
from app.services.drift import compute_rejection_rate


def test_rejection_rate_basic():
    data = [
        (CorrectionType.ACCEPTED.value, "s1"),
        (CorrectionType.REJECTED.value, "s2"),
        (CorrectionType.REJECTED.value, "s3"),
        (CorrectionType.MODIFIED.value, "s4"),
    ]
    assert compute_rejection_rate(data) == 0.5


def test_rejection_rate_empty():
    assert compute_rejection_rate([]) == 0.0


def test_rejection_rate_none_rejected():
    data = [(CorrectionType.ACCEPTED.value, "s1"), (CorrectionType.MODIFIED.value, "s2")]
    assert compute_rejection_rate(data) == 0.0
