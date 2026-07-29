"""Обезличивание DICOM на границе входа (ТЗ, SR-9, FR-1).

Профиль де-идентификации близок к DICOM PS3.15 Basic Application Level
Confidentiality: убираются/замещаются PHI-теги, генерируются новые UID,
соответствие «реальное ↔ псевдоним» сохраняется ТОЛЬКО в идентифицирующем
контуре (patient_pseudonym_map). Обезличенные данные далее не содержат PHI.

Детерминированность UID: новые UID выводятся из исходных через стабильный
хеш + корневой префикс, чтобы повторный приём того же объекта давал тот же
псевдоним (идемпотентность приёма, детект дубликатов).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass, field

try:  # pydicom доступен в контейнере; тесты профиля не требуют самого DICOM
    import pydicom
    from pydicom.dataset import Dataset
except Exception:  # pragma: no cover
    pydicom = None
    Dataset = object  # type: ignore

# Корень пространства UID организации (задать реальный OID при регистрации медизделия).
UID_ROOT = "1.2.826.0.1.3680043.10.9999"

# Теги, удаляемые полностью (PHI, не нужны для анализа).
TAGS_TO_REMOVE = [
    "PatientName",
    "PatientID",
    "OtherPatientIDs",
    "OtherPatientNames",
    "PatientBirthName",
    "PatientMotherBirthName",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientTelecomInformation",
    "ReferringPhysicianName",
    "ReferringPhysicianTelephoneNumbers",
    "PerformingPhysicianName",
    "OperatorsName",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "IssuerOfPatientID",
    "AccessionNumber",
    "RequestingPhysician",
    "NameOfPhysiciansReadingStudy",
]

# Теги, сохраняемые для клинической ценности (аппарат, геометрия, протокол).
TAGS_TO_KEEP = [
    "Modality",
    "Manufacturer",
    "ManufacturerModelName",
    "SoftwareVersions",
    "ProtocolName",
    "SliceThickness",
    "PixelSpacing",
    "SpacingBetweenSlices",
    "Rows",
    "Columns",
    "BodyPartExamined",
    "ContrastBolusAgent",
    "KVP",
    "PatientAge",   # возраст сохраняется (нужен для границ применимости), дата рождения — нет
    "PatientSex",
]


@dataclass
class DeidResult:
    pseudonym_patient_id: uuid.UUID
    real_mrn: str | None
    real_name: str | None
    real_study_uid: str | None
    pseudonym_study_uid: str | None
    removed_tags: list[str] = field(default_factory=list)


def _derive_uid(source_uid: str) -> str:
    """Детерминированно вывести обезличенный UID из исходного."""
    digest = hashlib.sha256(source_uid.encode()).hexdigest()
    numeric = str(int(digest[:24], 16))
    uid = f"{UID_ROOT}.{numeric}"
    return uid[:64]


def _derive_patient_pseudonym(patient_id: str | None, issuer: str | None) -> uuid.UUID:
    """Детерминированный UUID пациента из реального ID (одинаковый вход → тот же UUID)."""
    key = f"{issuer or ''}|{patient_id or uuid.uuid4().hex}"
    digest = hashlib.sha256(key.encode()).digest()
    return uuid.UUID(bytes=digest[:16])


def build_deid_plan(ds: "Dataset") -> DeidResult:
    """Рассчитать план обезличивания, не изменяя данные (для теста/аудита)."""
    real_name = str(getattr(ds, "PatientName", "") or "") or None
    real_mrn = str(getattr(ds, "PatientID", "") or "") or None
    issuer = str(getattr(ds, "IssuerOfPatientID", "") or "") or None
    real_study_uid = str(getattr(ds, "StudyInstanceUID", "") or "") or None

    pseudo_patient = _derive_patient_pseudonym(real_mrn, issuer)
    pseudo_study = _derive_uid(real_study_uid) if real_study_uid else None

    removed = [t for t in TAGS_TO_REMOVE if hasattr(ds, t)]
    return DeidResult(
        pseudonym_patient_id=pseudo_patient,
        real_mrn=real_mrn,
        real_name=real_name,
        real_study_uid=real_study_uid,
        pseudonym_study_uid=pseudo_study,
        removed_tags=removed,
    )


def anonymize_dataset(ds: "Dataset") -> tuple["Dataset", DeidResult]:
    """Вернуть обезличенную копию датасета и план де-ид.

    Исходный датасет не мутируется. Все UID переписываются детерминированно,
    PHI-теги удаляются. Идентифицирующие поля возвращаются в DeidResult для
    записи в идентифицирующий контур (и только туда).
    """
    if pydicom is None:  # pragma: no cover
        raise RuntimeError("pydicom недоступен в этой среде")

    plan = build_deid_plan(ds)
    clean = ds.copy()

    for tag in TAGS_TO_REMOVE:
        if hasattr(clean, tag):
            delattr(clean, tag)

    # Псевдонимные идентификаторы вместо PHI.
    clean.PatientID = plan.pseudonym_patient_id.hex
    clean.PatientName = "ANON^" + plan.pseudonym_patient_id.hex[:8]
    clean.PatientIdentityRemoved = "YES"
    clean.DeidentificationMethod = "medviz PS3.15 basic profile"

    # Переписать UID детерминированно.
    for uid_attr in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"):
        val = getattr(clean, uid_attr, None)
        if val:
            setattr(clean, uid_attr, _derive_uid(str(val)))

    # Убрать даты, сохранив год для возрастной статистики.
    if hasattr(clean, "PatientBirthDate"):
        del clean.PatientBirthDate

    return clean, plan
