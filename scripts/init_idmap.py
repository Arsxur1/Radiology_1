"""Создать таблицы идентифицирующего контура (SR-9) в отдельной БД.

Запускать один раз при развёртывании:
    docker compose exec backend python scripts/init_idmap.py
"""

from __future__ import annotations

from app.db.session import idmap_engine
from app.models.idmap import IdMapBase


def main() -> None:
    IdMapBase.metadata.create_all(bind=idmap_engine)
    print("Идентифицирующий контур: таблицы созданы.")


if __name__ == "__main__":
    main()
