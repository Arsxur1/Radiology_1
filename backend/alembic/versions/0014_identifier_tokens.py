"""Идентификаторы пациентов в доверенном контуре — только ключевые токены (SR-9).

patient_identifier.normalized_value хранил номер карты и ФИО (транслит) открытым текстом.
Миграция заменяет их на HMAC-токены с ключом площадки PSEUDONYM_KEY (app/core/pseudonym.py).
Нужен ключ: если строки есть, а ключа нет — миграция останавливается с пояснением.
Обратно не восстанавливается (downgrade ничего не делает): открытые значения уже удалены.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-02
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.core.pseudonym import TOKEN_PREFIX, identifier_token
    from app.services.patient_matching import normalize_identifier

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, id_type, normalized_value FROM patient_identifier WHERE normalized_value NOT LIKE :p"
    ), {"p": TOKEN_PREFIX + "%"}).fetchall()
    for row_id, id_type, value in rows:   # без ключа identifier_token остановит миграцию
        bind.execute(sa.text("UPDATE patient_identifier SET normalized_value = :v WHERE id = :i"),
                     {"v": identifier_token(id_type, normalize_identifier(value)), "i": row_id})


def downgrade() -> None:
    pass  # открытые значения не восстановить — и не нужно
