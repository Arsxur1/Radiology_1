"""Порядковый номер записей аудита (SR-8): однозначный порядок цепочки.

До этой версии порядок брался по created_at, а в PostgreSQL это время начала
транзакции — у записей одной транзакции оно совпадает, и проверка цепочки могла
ложно показать подделку. Номер выдаётся под блокировкой (services/audit.py).

Существующие записи нумеруются по самим ссылкам цепочки (prev_hash → entry_hash).
Журнал append-only: триггер запрета изменений отключается ТОЛЬКО на время этой
разметки в той же транзакции миграции и сразу включается обратно.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op
from app.db.migration_utils import has_column

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _chain_order(rows: list) -> list:
    """Порядок по ссылкам цепочки; ветвления (гонки прошлых версий) — по времени."""
    by_prev: dict = {}
    for r in rows:
        by_prev.setdefault(r.prev_hash, []).append(r)
    ordered, current, seen = [], None, set()
    while True:
        nxt = [r for r in by_prev.get(current, []) if r.id not in seen]
        if not nxt:
            break
        nxt.sort(key=lambda r: (r.created_at, str(r.id)))
        ordered.extend(nxt)
        seen.update(r.id for r in nxt)
        current = nxt[-1].entry_hash
    rest = sorted((r for r in rows if r.id not in seen), key=lambda r: (r.created_at, str(r.id)))
    return ordered + rest


def upgrade() -> None:
    if not has_column("audit_log", "seq"):
        op.add_column("audit_log", sa.Column("seq", sa.BigInteger(), nullable=True))
        op.create_index("ix_audit_log_seq", "audit_log", ["seq"], unique=True)
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, created_at, prev_hash, entry_hash FROM audit_log WHERE seq IS NULL")).fetchall()
    if not rows:
        return
    pg = bind.dialect.name == "postgresql"
    if pg:
        op.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_log_no_update")
    for n, r in enumerate(_chain_order(rows), start=1):
        bind.execute(sa.text("UPDATE audit_log SET seq = :n WHERE id = :id"), {"n": n, "id": r.id})
    if pg:
        op.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_log_no_update")


def downgrade() -> None:
    op.drop_index("ix_audit_log_seq", table_name="audit_log")
    op.drop_column("audit_log", "seq")
