"""Помощники идемпотентных миграций.

Начальная миграция 0001 создаёт схему из ТЕКУЩИХ моделей (Base.metadata), поэтому
на чистой базе колонки и таблицы последующих миграций уже существуют. Последующие
миграции добавляют объект только если его нет — одинаково работают и на чистой
базе, и на базе, прошедшей все шаги по очереди. В offline-режиме (--sql)
проверка невозможна — объект добавляется всегда (для обзора SQL).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op


def _inspector():
    return None if context.is_offline_mode() else sa.inspect(op.get_bind())


def has_table(table: str) -> bool:
    insp = _inspector()
    return bool(insp and insp.has_table(table))


def has_column(table: str, column: str) -> bool:
    insp = _inspector()
    return bool(insp and insp.has_table(table) and column in {c["name"] for c in insp.get_columns(table)})
