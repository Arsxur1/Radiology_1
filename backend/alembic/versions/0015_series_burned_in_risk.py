"""Series.burned_in_risk: возможен текст, впечатанный в пиксели (SR-9).

BurnedInAnnotation=YES или вторичная копия экрана (Secondary Capture). Такие серии не
идут в обучающие выгрузки и внешние отчёты.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-02
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    return "burned_in_risk" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("series")}


# 0001 создаёт таблицы по текущим моделям — на новой базе колонка уже есть.
def upgrade() -> None:
    if not _has_column():
        op.add_column("series", sa.Column("burned_in_risk", sa.Boolean(), nullable=False,
                                          server_default=sa.false()))


def downgrade() -> None:
    if _has_column():
        op.drop_column("series", "burned_in_risk")
