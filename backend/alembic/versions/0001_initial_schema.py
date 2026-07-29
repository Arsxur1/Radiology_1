"""Начальная схема доверенного контура (ТЗ, раздел 5).

Создаёт все таблицы модели данных из метаданных SQLAlchemy. Идентифицирующий
контур (patient_pseudonym_map) живёт в отдельной БД и создаётся своей миграцией.

Revision ID: 0001
Revises:
Create Date: 2026-07-29
"""
from __future__ import annotations

import app.models  # noqa: F401  (регистрирует таблицы в metadata)
from alembic import op
from app.db.base import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
