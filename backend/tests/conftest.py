"""Фикстуры для интеграционных тестов.

Используется in-memory SQLite через переносимые типы (app/db/types.py):
модели те же, продакшн-поведение (PostgreSQL) не меняется. Позволяет прогонять
сквозной путь без внешних сервисов.
"""

from __future__ import annotations

import os

# Ключ псевдонимизации для тестов (в рабочей системе — свой, из .env).
os.environ.setdefault("PSEUDONYM_KEY", "test-pseudonym-key-0123456789abcdef0123456789")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  регистрирует таблицы
from app.db.base import Base


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
