"""Таблица совмещения модальностей (ТЗ, FR-4).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID, JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("fixed_series_id", GUID(), sa.ForeignKey("series.id"), nullable=False, index=True),
        sa.Column("moving_series_id", GUID(), sa.ForeignKey("series.id"), nullable=False, index=True),
        sa.Column("stage", sa.Enum("rigid", "affine", "deformable", name="registration_stage"), nullable=False),
        sa.Column("metric_name", sa.String(64), nullable=False, server_default="mutual_information"),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("quality", JSONB, nullable=False, server_default="{}"),
        sa.Column("transform_ref", sa.String(512), nullable=True),
        sa.Column(
            "review_status",
            sa.Enum("pending", "approved", "rejected", name="registration_review"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("registration")
    op.execute("DROP TYPE IF EXISTS registration_stage")
    op.execute("DROP TYPE IF EXISTS registration_review")
