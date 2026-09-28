"""Область исследования из DICOM BodyPartExamined (ТЗ, SR-7).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.migration_utils import has_column

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_column("study", "body_part"):
        op.add_column("study", sa.Column("body_part", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("study", "body_part")
