"""Тест демо-наполнения (проверяет, что сквозной набор данных создаётся)."""

import sys
from pathlib import Path

# scripts/ не является пакетом — добавляем в путь для импорта.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from seed_demo import seed  # noqa: E402

from app.models.imaging import Study  # noqa: E402
from app.models.ml import Finding, ModelStatus, ModelVersion  # noqa: E402


def test_seed_creates_demo_data(db):
    result = seed(db)
    assert result["studies"] == 2

    # Активная модель, два исследования, находки со статусом pending (черновик ИИ).
    assert db.query(ModelVersion).filter(ModelVersion.status == ModelStatus.ACTIVE).count() == 1
    assert db.query(Study).count() == 2
    findings = db.query(Finding).all()
    assert len(findings) > 0
    assert all(f.confirmation_status.value == "pending" for f in findings)


def test_seed_is_idempotent(db):
    seed(db)
    again = seed(db)
    assert again == {"skipped": "already_seeded"}
    assert db.query(Study).count() == 2
