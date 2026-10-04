"""Patient.link_review / link_candidates: неоднозначное сопоставление при приёме (FR-1).

Раньше признак «нужна ручная привязка» писался только в аудит и никому не показывался:
врач не знал, что прошлые исследования пациента могут быть не видны, администратор — что
запись нужно сопоставить. Теперь признак хранится на пациенте.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-04
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.migration_utils import has_column
from app.db.types import JSONB

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


# 0001 создаёт таблицы по текущим моделям — на новой базе колонки уже есть.
def upgrade() -> None:
    if not has_column("patient", "link_review"):
        op.add_column("patient", sa.Column("link_review", sa.Boolean(), nullable=False,
                                           server_default=sa.false()))
    if not has_column("patient", "link_candidates"):
        op.add_column("patient", sa.Column("link_candidates", JSONB, nullable=True))


def downgrade() -> None:
    for col in ("link_candidates", "link_review"):
        if has_column("patient", col):
            op.drop_column("patient", col)
