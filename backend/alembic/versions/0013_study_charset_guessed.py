"""Study.charset_guessed: кодировка текста, угаданная при приёме.

Аппарат не указал SpecificCharacterSet — текст декодирован как UTF-8 или запасная
кодировка учреждения. Нужна для отчёта «Готовность данных площадки».

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-01
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    return "charset_guessed" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("study")}


# 0001 создаёт таблицы по текущим моделям — на новой базе колонка уже есть.
def upgrade() -> None:
    if not _has_column():
        op.add_column("study", sa.Column("charset_guessed", sa.String(32), nullable=True))


def downgrade() -> None:
    if _has_column():
        op.drop_column("study", "charset_guessed")
