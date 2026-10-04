"""Роль medviz_audit — без пароля (раньше создавалась с известным паролем «change_me_audit»).

Приложение этой ролью не входит; роль с известным паролем давала бы вход в базу с правом
писать в журнал аудита. Revision ID: 0019, Revises: 0018, Create Date: 2026-10-04
"""
from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'medviz_audit') THEN
                    ALTER ROLE medviz_audit PASSWORD NULL;
                END IF;
            END
            $$;
        """)


def downgrade() -> None:
    # Известный пароль не возвращаем.
    pass
