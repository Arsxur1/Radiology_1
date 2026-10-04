"""Инвентаризация хранимых данных (политика хранения, `docs/KHRANENIE-DANNYKH.md`).

Что платформа хранит, сколько записей и с какой даты — по категориям политики. Только
счётчики и даты, без идентификаторов: результат можно приложить к акту (например, до и
после удаления по окончании договора) и передать за пределы NCMC.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.idmap import PatientPseudonymMap
from app.models.imaging import Series, Study
from app.models.incident import Incident
from app.models.ml import AiRefusal, Correction, Finding, InferenceResult, ModelVersion, Report
from app.models.patient import Patient, PatientIdentifier
from app.models.registration import Registration

# (ключ, модель, что это, контур, категория политики хранения)
CATEGORIES = (
    ("patients", Patient, "Пациенты (внутренние UUID)", "доверенный", "медицинские"),
    ("patient_identifiers", PatientIdentifier, "Ключевые токены идентификаторов", "доверенный", "медицинские"),
    ("studies", Study, "Исследования (обезличенные метаданные)", "доверенный", "медицинские"),
    ("series", Series, "Серии", "доверенный", "медицинские"),
    ("findings", Finding, "Находки (ИИ и врача)", "доверенный", "медицинские"),
    ("reports", Report, "Заключения", "доверенный", "медицинские"),
    ("registrations", Registration, "Совмещения модальностей", "доверенный", "медицинские"),
    ("corrections", Correction, "Решения и правки врачей", "доверенный", "обучающие"),
    ("inference_results", InferenceResult, "Запуски моделей", "доверенный", "обучающие"),
    ("ai_refusals", AiRefusal, "Отказы ИИ вне границ", "доверенный", "контроль качества"),
    ("model_versions", ModelVersion, "Версии моделей и свидетельства", "доверенный", "контроль качества"),
    ("incidents", Incident, "Инциденты", "доверенный", "контроль качества"),
    ("audit_log", AuditLog, "Журнал аудита", "доверенный", "аудит"),
)


def _row(db: Session, model) -> dict:
    n, first, last = db.execute(
        select(func.count(), func.min(model.created_at), func.max(model.created_at)).select_from(model)
    ).one()
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"records": int(n), "oldest": iso(first), "newest": iso(last)}


def build_inventory(db: Session, idmap_db: Session | None = None) -> dict:
    items = []
    for key, model, label, contour, category in CATEGORIES:
        items.append({"key": key, "label": label, "contour": contour, "category": category, **_row(db, model)})
    if idmap_db is not None:
        items.append({"key": "pseudonym_map", "label": "Связь псевдоним ↔ ФИО, номер карты, исходные UID",
                      "contour": "идентифицирующий", "category": "идентифицирующие",
                      **_row(idmap_db, PatientPseudonymMap)})
    excluded = db.execute(select(func.count()).select_from(Patient)
                          .where(Patient.training_excluded.is_(True))).scalar_one()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "items": items,
        "patients_training_excluded": int(excluded),
        "note": "Снимки (Orthanc, хранилище объектов), резервные копии и логи учитываются отдельно — "
                "см. KHRANENIE-DANNYKH.md, раздел «Проверка удаления».",
    }
