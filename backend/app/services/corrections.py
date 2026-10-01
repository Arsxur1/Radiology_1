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

from sqlalchemy import select
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


# Причины отклонения находки модели — закрытый список (SR-6). Свободный текст был бы
# плохим обучающим сигналом и мог бы содержать ФИО; код причины — чистый агрегат.
REJECT_REASONS: dict[str, str] = {
    "false_positive": "Находки нет (ложное срабатывание)",
    "wrong_finding": "Есть другая находка (неверный код)",
    "wrong_location": "Неверная локализация / контур",
    "artifact": "Артефакт, укладка, посторонний предмет",
    "not_significant": "Клинически незначимо",
    "poor_quality": "Качество снимка не позволяет оценить",
}


def _check_reason(reason: str | None) -> str | None:
    if reason in (None, ""):
        return None
    if reason not in REJECT_REASONS:
        raise CorrectionError(f"Неизвестная причина отклонения: {reason!r}")
    return reason


def _last_rejection(db: Session, finding_id: uuid.UUID) -> Correction | None:
    return db.execute(
        select(Correction)
        .where(Correction.finding_id == finding_id, Correction.correction_type == CorrectionType.REJECTED)
        .order_by(Correction.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def reject_reason_of(db: Session, finding_id: uuid.UUID) -> str | None:
    c = _last_rejection(db, finding_id)
    return (c.after or {}).get("reject_reason") if c else None


def _get_actionable(db: Session, finding_id: uuid.UUID) -> Finding:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise CorrectionError("Находка не найдена")
    # Результат теневого прогона врачу не показывается — и действий по нему нет.
    if finding.inference_result is not None and finding.inference_result.shadow_run:
        raise CorrectionError("Находка теневого прогона недоступна для действий врача")
    return finding


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
    finding = _get_actionable(db, finding_id)
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
    finding = _get_actionable(db, finding_id)

    before = _snapshot(finding)
    if new_measurements is not None:
        finding.measurements = new_measurements
    if new_code is not None:
        if new_code.startswith("CXR-"):
            from app.services.finding_vocabulary import by_code

            concept = by_code(new_code)
            if concept is None:
                raise CorrectionError(f"Код {new_code} отсутствует в словаре находок")
            if new_label is None:
                new_label = concept.label_ru
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
    reason = _check_reason(reason)
    finding = _get_actionable(db, finding_id)

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
        extra={"reject_reason": reason} if reason else None,
    )


def set_reject_reason(db: Session, *, finding_id: uuid.UUID, physician: str, reason: str) -> Correction:
    """Уточнить причину уже отклонённой находки (необязательный второй шаг SR-6).

    Отклонение — одно действие; причина выбирается после, из закрытого списка. Менять
    её может только тот врач, который отклонил. Каждое уточнение — в журнале аудита.
    """
    reason = _check_reason(reason)
    if reason is None:
        raise CorrectionError("Причина не указана")
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise CorrectionError("Находка не найдена")
    correction = _last_rejection(db, finding_id)
    if finding.confirmation_status != ConfirmationStatus.REJECTED or correction is None:
        raise CorrectionError("Находка не отклонена")
    if correction.author != physician:
        raise CorrectionError("Причину указывает врач, отклонивший находку")
    correction.after = {**(correction.after or {}), "reject_reason": reason}
    db.flush()
    audit.record(
        db, actor=physician, actor_role="radiologist", action=AuditAction.FINDING_REJECT,
        entity_type="finding", entity_id=finding.id,
        details={"reject_reason": reason, "reason_update": True},
    )
    return correction


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
    Коды словаря ОГК (CXR-…) проверяются; подпись и кодовая система — из словаря.
    """
    if code and code.startswith("CXR-"):
        from sqlalchemy import select

        from app.services.finding_vocabulary import CODING_SYSTEM, by_code

        concept = by_code(code)
        if concept is None:
            raise CorrectionError(f"Код {code} отсутствует в словаре находок")
        label = label or concept.label_ru
        coding_system = CODING_SYSTEM
        existing = db.execute(
            select(Finding).where(
                Finding.series_id == series_id,
                Finding.code == code,
                Finding.confirmation_status == ConfirmationStatus.CONFIRMED,
            )
        ).scalars().first()
        if existing is not None:
            raise CorrectionError(f"Находка {code} уже отмечена в этой серии")
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
    extra: dict | None = None,
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
            **(extra or {}),
        },
    )
    return correction
