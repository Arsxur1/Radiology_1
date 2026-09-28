"""Адаптер инференса модели (свои веса / открытая предобученная модель).

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.migration_utils import has_column
from app.db.types import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_column("model_version", "adapter"):
        op.add_column("model_version", sa.Column("adapter", JSONB, nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("model_version", "adapter")
