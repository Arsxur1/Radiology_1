"""Модели классификации находок и теневой прогон (ТЗ, FR-10, SR-1).

model_version.task — тип модели (segmentation | classification);
model_version.operating_points — пороги по кодам находок (по валидации);
inference_result.shadow_run — результат теневого прогона, врачу не показывается.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.types import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_version",
        sa.Column("task", sa.String(32), nullable=False, server_default="segmentation"),
    )
    op.add_column(
        "model_version",
        sa.Column("operating_points", JSONB, nullable=False, server_default="{}"),
    )
    op.add_column(
        "inference_result",
        sa.Column("shadow_run", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("inference_result", "shadow_run")
    op.drop_column("model_version", "operating_points")
    op.drop_column("model_version", "task")
