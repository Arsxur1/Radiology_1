"""Инвентаризация хранимых данных — для акта (до и после удаления, ежегодная проверка).

    docker compose run --rm backend python scripts/data_inventory.py > inventory-$(date +%F).json

Только счётчики и даты, без идентификаторов. Снимки, копии и логи проверяются отдельно
(docs/KHRANENIE-DANNYKH.md, «Проверка удаления»).
"""

from __future__ import annotations

import json

from app.db.session import IdMapSessionLocal, SessionLocal
from app.services.data_inventory import build_inventory


def main() -> None:
    with SessionLocal() as db, IdMapSessionLocal() as idmap:
        print(json.dumps(build_inventory(db, idmap), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
