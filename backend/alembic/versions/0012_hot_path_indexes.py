"""Индексы горячих связей: прогоны по версии модели, находки по прогону.

Отчёт теневого прогона, калибровка и истина врача выбирают по этим ключам; на году
работы клиники без индексов это полные просмотры таблиц.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-01
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_inference_result_model_version_id", "inference_result", ["model_version_id"]),
    ("ix_finding_inference_result_id", "finding", ["inference_result_id"]),
)


def _existing(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    for name, table, cols in INDEXES:
        if name not in _existing(table):
            op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _ in INDEXES:
        if name in _existing(table):
            op.drop_index(name, table_name=table)
