"""Patient.training_excluded: отзыв согласия на использование данных для обучения.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-04
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.migration_utils import has_column

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


# 0001 создаёт таблицы по текущим моделям — на новой базе колонка уже есть.
def upgrade() -> None:
    if not has_column("patient", "training_excluded"):
        op.add_column("patient", sa.Column("training_excluded", sa.Boolean(), nullable=False,
                                           server_default=sa.false()))


def downgrade() -> None:
    if has_column("patient", "training_excluded"):
        op.drop_column("patient", "training_excluded")
