"""Журнал инцидентов (ТЗ, раздел 9 п. 7) и действие аудита INCIDENT.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-02
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.migration_utils import has_table
from app.db.types import GUID

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_KIND = ("AI_MISLEADING", "AI_MISSED", "WRONG_PATIENT", "SYSTEM_FAILURE", "PRIVACY", "OTHER")
_SEVERITY = ("NEAR_MISS", "MODERATE", "SERIOUS")
_STATUS = ("NEW", "INVESTIGATING", "CLOSED")


# 0001 создаёт таблицы по текущим моделям — на новой базе таблица уже есть.
def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'INCIDENT'")
    if has_table("incident"):
        return
    op.create_table(
        "incident",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reported_by", sa.String(128), nullable=False),
        sa.Column("reporter_role", sa.String(64), nullable=True),
        sa.Column("kind", sa.Enum(*_KIND, name="incident_kind"), nullable=False),
        sa.Column("severity", sa.Enum(*_SEVERITY, name="incident_severity"), nullable=False),
        sa.Column("status", sa.Enum(*_STATUS, name="incident_status"), nullable=False),
        sa.Column("study_id", GUID(), sa.ForeignKey("study.id"), nullable=True),
        sa.Column("finding_id", GUID(), sa.ForeignKey("finding.id"), nullable=True),
        sa.Column("model_version_id", GUID(), sa.ForeignKey("model_version.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("closed_by", sa.String(128), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Значение INCIDENT в типе audit_action остаётся (PostgreSQL не удаляет значения enum).
    if has_table("incident"):
        op.drop_table("incident")
    if op.get_bind().dialect.name == "postgresql":
        for name in ("incident_kind", "incident_severity", "incident_status"):
            op.execute(f"DROP TYPE IF EXISTS {name}")
