"""Надгробие объединения пациентов (ТЗ, FR-1: история merge/split).

Добавляет patient.merged_into_id — ссылку на пациента, в которого объединена
запись. Активный пациент имеет NULL. Строки не удаляются (сохраняется история).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-29
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.migration_utils import has_column
from app.db.types import GUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if has_column("patient", "merged_into_id"):
        return  # создано начальной миграцией из текущих моделей
    op.add_column("patient", sa.Column("merged_into_id", GUID(), nullable=True))
    op.create_foreign_key(
        "fk_patient_merged_into", "patient", "patient", ["merged_into_id"], ["id"]
    )


def downgrade() -> None:
    # Ограничение есть только если колонку добавила эта миграция (а не 0001).
    op.execute("ALTER TABLE patient DROP CONSTRAINT IF EXISTS fk_patient_merged_into")
    op.drop_column("patient", "merged_into_id")
