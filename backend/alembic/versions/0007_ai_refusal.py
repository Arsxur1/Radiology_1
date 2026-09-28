"""Учёт отказов моделей по границам применимости (ТЗ, SR-7, FR-11).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-28
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID, JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_refusal",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("series_id", GUID(), sa.ForeignKey("series.id"), nullable=False, index=True),
        sa.Column("model_version_id", GUID(), sa.ForeignKey("model_version.id"), nullable=False, index=True),
        sa.Column("reasons", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("ai_refusal")
