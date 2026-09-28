"""Тест демо-наполнения (проверяет, что сквозной набор данных создаётся)."""

import sys
from pathlib import Path

# scripts/ не является пакетом — добавляем в путь для импорта.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import seed_demo as seed_demo_module  # noqa: E402
from seed_demo import seed  # noqa: E402

from app.models.imaging import Study  # noqa: E402
from app.models.ml import Finding, ModelStatus, ModelVersion  # noqa: E402


def test_seed_creates_demo_data(db):
    result = seed(db)
    assert result["studies"] == 3

    # Активные модели (сегментация + классификатор), кандидат в SHADOW, находки pending.
    assert db.query(ModelVersion).filter(ModelVersion.status == ModelStatus.ACTIVE).count() == 2
    assert db.query(ModelVersion).filter(ModelVersion.status == ModelStatus.SHADOW).count() == 1
    assert db.query(Study).count() == 3
    findings = db.query(Finding).all()
    assert len(findings) > 0
    assert all(f.confirmation_status.value == "pending" for f in findings)


def test_seed_is_idempotent(db):
    seed(db)
    again = seed(db)
    assert again == {"skipped": "already_seeded"}
    assert db.query(Study).count() == 3


def test_synthetic_cxr_is_valid_dicom():
    import io

    import pydicom

    ds = pydicom.dcmread(io.BytesIO(seed_demo_module.synthetic_cxr_dicom("1.2.3", "1.2.3.4", "1.2.3.4.5", size=32)))
    assert ds.Modality == "DX" and ds.Rows == 32 and len(ds.PixelData) == 32 * 32 * 2
