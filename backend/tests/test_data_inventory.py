"""Инвентаризация данных для политики хранения: агрегаты без идентификаторов."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_classification import _finalize, _series  # noqa: E402

from app.models.idmap import IdMapBase, PatientPseudonymMap  # noqa: E402
from app.services.data_inventory import CATEGORIES, build_inventory  # noqa: E402


def test_counts_dates_and_no_identifiers(db):
    s = _series(db, uid="inv-1")
    _finalize(db, s)
    _series(db, uid="inv-2")
    db.commit()
    engine = create_engine("sqlite://")
    IdMapBase.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as idmap:
        idmap.add(PatientPseudonymMap(pseudonym_patient_id=s.study.patient_id, real_mrn="SECRET-MRN-1",
                                      real_name="Секретов Ребёнок"))
        idmap.commit()
        inv = build_inventory(db, idmap)
    by = {i["key"]: i for i in inv["items"]}
    assert set(by) == {k for k, *_ in CATEGORIES} | {"pseudonym_map"}
    assert by["studies"]["records"] == 2 and by["reports"]["records"] == 1
    assert by["studies"]["oldest"] and by["pseudonym_map"]["contour"] == "идентифицирующий"
    assert by["pseudonym_map"]["records"] == 1
    text = json.dumps(inv, ensure_ascii=False)
    assert "SECRET" not in text and "Секретов" not in text and "inv-1" not in text
    assert build_inventory(db)["patients_training_excluded"] == 0     # без идентифицирующей БД — тоже работает
