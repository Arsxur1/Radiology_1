"""Захват правок врача как обучающего сигнала (ТЗ, FR-9, SR-2, SR-6).

Врач не размечает данные — он работает, а разметка получается как побочный
результат. Каждое решение (подтвердить / изменить / отклонить) порождает запись
`correction` вместе с исходными данными и версией модели.

Инварианты:
- SR-2: включение результата в заключение — активное действие врача. Нет
  «принять всё» и авто-принятия: подтверждается ровно одна находка за вызов.
- SR-6: отклонение фиксируется как обучающий сигнал.
- Разделение «модель посчитала» / «врач подтвердил» проходит через
  `Finding.confirmation_status` и `Finding.source`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.audit import AuditAction
from app.models.ml import (
    ConfirmationStatus,
    Correction,
    CorrectionType,
    Finding,
    FindingSource,
)
from app.services import audit


class CorrectionError(Exception):
    """Нарушение инварианта захвата правок."""


def _resolve_model_version_id(db: Session, finding: Finding) -> uuid.UUID | None:
    if finding.inference_result is not None:
        return finding.inference_result.model_version_id
    return None


def confirm_finding(
    db: Session,
    *,
    finding_id: uuid.UUID,
    physician: str,
    time_spent_seconds: float | None = None,
) -> Correction:
    """Врач подтверждает находку модели без изменений (тип ACCEPTED).

    Активное действие по одной находке (SR-2). Порождает correction — обучающий
    сигнал «модель была права».
    """
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise CorrectionError("Находка не найдена")
    if finding.confirmation_status == ConfirmationStatus.CONFIRMED:
        raise CorrectionError("Находка уже подтверждена")

    before = _snapshot(finding)
    finding.confirmation_status = ConfirmationStatus.CONFIRMED
    finding.confirmed_by = physician
    db.flush()

    correction = _record_correction(
        db,
        finding=finding,
        correction_type=CorrectionType.ACCEPTED,
        before=before,
        after=_snapshot(finding),
        physician=physician,
        time_spent_seconds=time_spent_seconds,
        action=AuditAction.FINDING_CONFIRM,
    )
    return correction


def modify_finding(
    db: Session,
    *,
    finding_id: uuid.UUID,
    physician: str,
    new_measurements: dict | None = None,
    new_code: str | None = None,
    new_label: str | None = None,
    new_coordinates: dict | None = None,
    time_spent_seconds: float | None = None,
) -> Correction:
    """Врач правит находку (тип MODIFIED). Сохраняется было/стало.

    Правка — сильнейший обучающий сигнал: показывает, каким должен быть верный
    результат. После правки находка считается подтверждённой врачом.
    """
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise CorrectionError("Находка не найдена")

    before = _snapshot(finding)
    if new_measurements is not None:
        finding.measurements = new_measurements
    if new_code is not None:
        finding.code = new_code
    if new_label is not None:
        finding.label = new_label
    if new_coordinates is not None:
        finding.coordinates = new_coordinates
    finding.confirmation_status = ConfirmationStatus.CONFIRMED
    finding.confirmed_by = physician
    db.flush()

    return _record_correction(
        db,
        finding=finding,
        correction_type=CorrectionType.MODIFIED,
        before=before,
        after=_snapshot(finding),
        physician=physician,
        time_spent_seconds=time_spent_seconds,
        action=AuditAction.CORRECTION,
    )


def reject_finding(
    db: Session,
    *,
    finding_id: uuid.UUID,
    physician: str,
    reason: str | None = None,
    time_spent_seconds: float | None = None,
) -> Correction:
    """Врач отклоняет находку целиком одним действием (SR-6).

    Обучающий сигнал «ложное срабатывание». Также питает контроль дрейфа
    (доля отклонений по срезам, FR-11).
    """
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise CorrectionError("Находка не найдена")

    before = _snapshot(finding)
    finding.confirmation_status = ConfirmationStatus.REJECTED
    finding.confirmed_by = physician
    db.flush()

    after = _snapshot(finding)
    if reason:
        after["reject_reason"] = reason
    return _record_correction(
        db,
        finding=finding,
        correction_type=CorrectionType.REJECTED,
        before=before,
        after=after,
        physician=physician,
        time_spent_seconds=time_spent_seconds,
        action=AuditAction.FINDING_REJECT,
    )


def create_physician_finding(
    db: Session,
    *,
    series_id: uuid.UUID,
    physician: str,
    measurements: dict,
    code: str | None = None,
    label: str | None = None,
    coordinates: dict | None = None,
    coding_system: str = "RadLex",
    time_spent_seconds: float | None = None,
) -> Finding:
    """Врач добавляет находку, которую модель не выдала (пропуск модели).

    Источник — physician, статус сразу CONFIRMED. Порождает correction типа
    MODIFIED (было пусто → стало находкой): обучающий сигнал «модель пропустила».
    """
    finding = Finding(
        series_id=series_id,
        inference_result_id=None,
        coding_system=coding_system,
        code=code,
        label=label,
        measurements=measurements,
        coordinates=coordinates,
        source=FindingSource.PHYSICIAN,
        confirmation_status=ConfirmationStatus.CONFIRMED,
        confirmed_by=physician,
    )
    db.add(finding)
    db.flush()

    _record_correction(
        db,
        finding=finding,
        correction_type=CorrectionType.MODIFIED,
        before=None,
        after=_snapshot(finding),
        physician=physician,
        time_spent_seconds=time_spent_seconds,
        action=AuditAction.CORRECTION,
    )
    return finding


def _snapshot(finding: Finding) -> dict:
    """Снимок значимых полей находки для истории было/стало."""
    return {
        "code": finding.code,
        "label": finding.label,
        "coding_system": finding.coding_system,
        "measurements": finding.measurements,
        "coordinates": finding.coordinates,
        "source": finding.source.value if finding.source else None,
        "confirmation_status": finding.confirmation_status.value,
    }


def _record_correction(
    db: Session,
    *,
    finding: Finding,
    correction_type: CorrectionType,
    before: dict | None,
    after: dict | None,
    physician: str,
    time_spent_seconds: float | None,
    action: AuditAction,
) -> Correction:
    correction = Correction(
        finding_id=finding.id,
        series_id=finding.series_id,
        correction_type=correction_type,
        before=before,
        after=after,
        author=physician,
        time_spent_seconds=time_spent_seconds,
    )
    db.add(correction)
    db.flush()

    audit.record(
        db,
        actor=physician,
        actor_role="radiologist",
        action=action,
        entity_type="finding",
        entity_id=finding.id,
        details={
            "correction_type": correction_type.value,
            "model_version_id": str(_resolve_model_version_id(db, finding) or ""),
            "time_spent_seconds": time_spent_seconds,
        },
    )
    return correction
