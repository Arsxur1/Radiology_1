"""Переносимые типы столбцов.

В продакшне (PostgreSQL) используются нативные UUID и JSONB. В тестах на SQLite
те же модели работают через переносимые представления (CHAR(32) для UUID, JSON
для JSONB). Продакшн-поведение не меняется — вариант PostgreSQL приоритетен.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CHAR, JSON
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator

#: JSONB в PostgreSQL, обычный JSON в остальных диалектах (для тестов).
JSONB = JSON().with_variant(PG_JSONB(), "postgresql")


class GUID(TypeDecorator):
    """UUID-столбец: нативный UUID в PostgreSQL, CHAR(32) в SQLite."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return value
        return value.hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))
