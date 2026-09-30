"""Наблюдатель приёмного узла orthanc-raw (ТЗ, FR-1): от C-STORE к обезличиванию.

PACS/аппарат присылает снимки в orthanc-raw (AE MEDVIZ_RAW). Наблюдатель читает
журнал изменений Orthanc (/changes) и ставит каждый новый инстанс в очередь
`ingest.process_raw_instance` (обезличивание → clean-Orthanc + MinIO → БД → автоанализ).

Курсор журнала хранится в Redis: после перезапуска обработка продолжается с места
остановки. Если курсор потерян, журнал читается с начала — приём идемпотентен
(дубликаты распознаются по UID), поэтому повтор безопасен.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orthanc_watcher")

CURSOR_KEY = "medviz:orthanc-raw:changes-cursor"
# Пульс: время последнего УСПЕШНОГО опроса — по нему «Состояние системы» видит, жив ли приём.
HEARTBEAT_KEY = "medviz:orthanc-watcher:heartbeat"
POLL_SECONDS = 2.0


class RedisCursor:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url)

    def get(self) -> int:
        v = self._r.get(CURSOR_KEY)
        return int(v) if v is not None else 0

    def set(self, value: int) -> None:
        self._r.set(CURSOR_KEY, value)

    def beat(self) -> None:
        self._r.set(HEARTBEAT_KEY, str(time.time()), ex=3600)


def poll_once(client, cursor, dispatch: Callable[[str], None], limit: int = 100) -> int:
    """Прочитать журнал до конца, отправить новые инстансы. Возвращает число отправленных.

    Курсор сдвигается после каждой страницы — только когда все её инстансы отправлены.
    """
    sent = 0
    while True:
        since = cursor.get()
        data = client.get_changes(since=since, limit=limit)
        for change in data.get("Changes", []):
            if change.get("ChangeType") == "NewInstance":
                dispatch(change["ID"])
                sent += 1
        last = int(data.get("Last", since))
        if last > since:
            cursor.set(last)
        if data.get("Done", True) or last <= since:
            return sent


def main() -> None:  # pragma: no cover - бесконечный цикл сервиса
    from app.services.orthanc import raw_client
    from app.workers.tasks import process_raw_instance

    cursor = RedisCursor(get_settings().redis_url)
    logger.info("Наблюдение за orthanc-raw, курсор журнала: %s", cursor.get())
    while True:
        client = raw_client()
        try:
            n = poll_once(client, cursor, lambda iid: process_raw_instance.delay(iid))
            cursor.beat()
            if n:
                logger.info("Поставлено в обработку: %d", n)
        except Exception:  # noqa: BLE001 - Orthanc/Redis временно недоступны — повторим
            logger.exception("Ошибка опроса orthanc-raw")
        finally:
            client.close()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
