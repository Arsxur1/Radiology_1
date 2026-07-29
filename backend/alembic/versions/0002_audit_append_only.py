"""Аудит-лог только на добавление (ТЗ, SR-8).

Изменение и удаление записей audit_log невозможно на уровне СУБД:
1) триггер, поднимающий исключение на UPDATE/DELETE;
2) отзыв прав UPDATE/DELETE у ролей приложения;
3) отдельная роль medviz_audit с правом только INSERT/SELECT.

Так подмена аудит-лога средствами приложения становится невозможной
(критерий приёмки, раздел 10).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-29
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Триггер, запрещающий изменение и удаление.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_no_mutate()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log является append-only: % запрещён', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_no_update
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_no_mutate();
        """
    )
    # Отозвать права изменения/удаления у всех (кроме владельца схемы).
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM PUBLIC;")

    # Роль только для добавления/чтения аудита.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'medviz_audit') THEN
                CREATE ROLE medviz_audit LOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT INSERT, SELECT ON audit_log TO medviz_audit;")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM medviz_audit;")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_no_mutate();")
