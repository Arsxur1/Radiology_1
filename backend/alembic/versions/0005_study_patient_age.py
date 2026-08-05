"""Возраст пациента на момент исследования (ТЗ, SR-7).

Нужен для проверки границ применимости (взрослые/дети раздельно). Извлекается
из DICOM PatientAge при приёме; дата рождения при обезличивании удаляется.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-29
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("study", sa.Column("patient_age_years", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("study", "patient_age_years")
