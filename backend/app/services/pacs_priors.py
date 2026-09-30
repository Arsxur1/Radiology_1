"""Предыдущие исследования пациента из PACS клиники (FR-1, FR-7).

Врачу для сравнения нужны прошлые снимки того же ребёнка, которые лежат в H-PACS,
но ещё не приходили в платформу. Путь:

  1. По обезличенному исследованию находим настоящий номер карты — только в
     идентифицирующем контуре (idmap), в доверенный контур он не попадает.
  2. C-FIND в PACS по номеру карты.
  3. Врачу возвращаются дата, модальность, описание и число серий — без ФИО, номера
     карты и исходных UID. Вместо UID — непрозрачный токен (HMAC от UID).
  4. По токену — повторный C-FIND и C-MOVE на приёмный узел (orthanc-raw). Дальше
     обычный путь: обезличивание → связывание с тем же псевдопациентом по номеру карты.

Исследования, уже принятые в платформу, помечаются и ведут на свою карточку.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.idmap import PatientPseudonymMap
from app.models.imaging import Study
from app.services import pacs
from app.services.pacs import PacsNode, StudyQuery


class PriorsUnavailable(Exception):
    """Нельзя выполнить поиск: нет номера карты, PACS не настроен или недоступен."""


@dataclass
class PriorStudy:
    token: str
    study_date: str | None
    modality: str | None
    description: str | None
    series_count: int | None
    is_current: bool
    imported_study_id: uuid.UUID | None


def study_token(study_instance_uid: str) -> str:
    from app.core.config import get_settings

    key = get_settings().backend_secret_key.encode()
    return hmac.new(key, study_instance_uid.encode(), hashlib.sha256).hexdigest()[:32]


def _patient_mrn(idmap: Session, patient_id: uuid.UUID) -> str | None:
    return idmap.execute(
        select(PatientPseudonymMap.real_mrn)
        .where(PatientPseudonymMap.pseudonym_patient_id == patient_id,
               PatientPseudonymMap.real_mrn.is_not(None), PatientPseudonymMap.real_mrn != "")
        .order_by(PatientPseudonymMap.created_at.desc())
    ).scalars().first()


def _search(db: Session, idmap: Session, study: Study, node: PacsNode | None, finder):
    if node is None:
        raise PriorsUnavailable("Узел PACS не настроен (PACS_AET/PACS_HOST/PACS_PORT в .env)")
    mrn = _patient_mrn(idmap, study.patient_id)
    if not mrn:
        raise PriorsUnavailable("Номер карты пациента неизвестен — искать в PACS не по чему")
    try:
        outcome = finder(node, StudyQuery(patient_id=mrn))
    except pacs.PacsUnavailable as e:
        raise PriorsUnavailable(str(e)) from e
    # Защита от «широких» ответов PACS: берём только исследования с тем же номером карты.
    return [s for s in outcome.studies if s.study_instance_uid and (s.patient_id or mrn) == mrn]


def find_priors(db: Session, idmap: Session, study: Study, *, node: PacsNode | None,
                finder=pacs.find_studies) -> list[PriorStudy]:
    found = _search(db, idmap, study, node, finder)
    uids = [s.study_instance_uid for s in found]
    pseudo_by_real = dict(idmap.execute(
        select(PatientPseudonymMap.real_study_instance_uid, PatientPseudonymMap.pseudonym_study_instance_uid)
        .where(PatientPseudonymMap.real_study_instance_uid.in_(uids))
    ).all()) if uids else {}
    study_by_pseudo = dict(db.execute(
        select(Study.study_instance_uid, Study.id).where(Study.study_instance_uid.in_(pseudo_by_real.values()))
    ).all()) if pseudo_by_real else {}
    out = []
    for s in found:
        imported = study_by_pseudo.get(pseudo_by_real.get(s.study_instance_uid))
        out.append(PriorStudy(
            token=study_token(s.study_instance_uid), study_date=s.study_date, modality=s.modality,
            description=s.description, series_count=s.series_count,
            is_current=imported == study.id, imported_study_id=imported,
        ))
    return sorted(out, key=lambda p: p.study_date or "", reverse=True)


def retrieve_prior(db: Session, idmap: Session, study: Study, token: str, *, node: PacsNode | None,
                   finder=pacs.find_studies, mover=pacs.move_study) -> bool:
    """Запросить у PACS выгрузку исследования по токену. LookupError — токен не найден."""
    found = _search(db, idmap, study, node, finder)
    match = next((s for s in found if hmac.compare_digest(study_token(s.study_instance_uid), token)), None)
    if match is None:
        raise LookupError("Исследование не найдено среди исследований этого пациента в PACS")
    try:
        return mover(node, match.study_instance_uid)
    except pacs.PacsUnavailable as e:
        raise PriorsUnavailable(str(e)) from e
