"""Роли и права (ТЗ, FR-12). Источник ролей — Keycloak (OIDC realm roles)."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"                 # администратор: настройки, смена режимов
    RADIOLOGIST = "radiologist"     # врач-рентгенолог: подтверждение находок, правки
    CLINICIAN = "clinician"         # клиницист: просмотр и подтверждённые заключения
    RESEARCHER = "researcher"       # инженер-исследователь: только обезличенные данные
    AUDITOR = "auditor"             # аудитор: только чтение журналов


#: Кто может менять режим работы (раздел 2)
CAN_CHANGE_MODE = {Role.ADMIN}

#: Кто может подтверждать/править находки (SR-2, SR-6)
CAN_CONFIRM_FINDINGS = {Role.RADIOLOGIST}

#: Кто видит только обезличенные данные
DEIDENTIFIED_ONLY = {Role.RESEARCHER}

#: Кто может читать аудит-лог
CAN_READ_AUDIT = {Role.AUDITOR, Role.ADMIN}
