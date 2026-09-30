"""Свидетельства для гейта продвижения: результат замороженного теста (FR-10).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.migration_utils import has_column
from app.db.types import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_column("model_version", "evidence"):
        op.add_column("model_version", sa.Column("evidence", JSONB, nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("model_version", "evidence")
