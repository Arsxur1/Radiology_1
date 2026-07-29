"""Сессии БД: доверенный контур и (отдельно) идентифицирующий контур."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Идентифицирующий контур — отдельный движок к изолированной БД (SR-9).
idmap_engine = create_engine(_settings.idmap_database_url, pool_pre_ping=True, future=True)
IdMapSessionLocal = sessionmaker(bind=idmap_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_idmap_db() -> Iterator[Session]:
    db = IdMapSessionLocal()
    try:
        yield db
    finally:
        db.close()
