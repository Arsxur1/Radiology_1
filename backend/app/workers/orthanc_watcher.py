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
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orthanc_watcher")

CURSOR_KEY = "medviz:orthanc-raw:changes-cursor"
# Досылка: снимок, пролежавший в orthanc-raw дольше STUCK_AFTER, не обработан (после
# успешного приёма исходник удаляется) — отправить заново, но не больше REDISPATCH_LIMIT раз.
RECONCILE_SECONDS = 300
STUCK_AFTER = timedelta(minutes=10)
REDISPATCH_LIMIT = 6
REDISPATCH_KEY = "medviz:orthanc-raw:redispatch:"
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


def stuck_instances(instances: list[tuple[str, str | None]], now: datetime) -> list[str]:
    """Инстансы, лежащие в orthanc-raw дольше STUCK_AFTER (время приёма — в UTC Orthanc)."""
    out = []
    for iid, received in instances:
        if not received:
            continue
        try:
            ts = datetime.strptime(received, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            continue
        if now - ts > STUCK_AFTER:
            out.append(iid)
    return out


def reconcile_once(client, counter, dispatch: Callable[[str], None], now: datetime | None = None) -> dict:
    """Дослать застрявшие снимки. counter(iid) -> сколько раз уже досылали (и +1)."""
    now = now or datetime.now(UTC)
    sent, given_up = 0, 0
    for iid in stuck_instances(client.instances_with_reception(), now):
        if counter(iid) > REDISPATCH_LIMIT:
            given_up += 1          # битый файл: не крутим бесконечно, видно в «Состоянии системы»
            continue
        dispatch(iid)
        sent += 1
    return {"redispatched": sent, "given_up": given_up}


def main() -> None:  # pragma: no cover - бесконечный цикл сервиса
    from app.services.orthanc import raw_client
    from app.workers.tasks import process_raw_instance

    cursor = RedisCursor(get_settings().redis_url)
    logger.info("Наблюдение за orthanc-raw, курсор журнала: %s", cursor.get())
    last_reconcile = 0.0

    def counter(iid: str) -> int:
        key = REDISPATCH_KEY + iid
        n = int(cursor._r.incr(key))
        cursor._r.expire(key, 7 * 86400)
        return n

    while True:
        client = raw_client()
        try:
            n = poll_once(client, cursor, lambda iid: process_raw_instance.delay(iid))
            cursor.beat()
            if time.monotonic() - last_reconcile > RECONCILE_SECONDS:
                last_reconcile = time.monotonic()
                r = reconcile_once(client, counter, lambda iid: process_raw_instance.delay(iid))
                if r["redispatched"] or r["given_up"]:
                    logger.warning("Досылка застрявших снимков orthanc-raw: %s", r)
            if n:
                logger.info("Поставлено в обработку: %d", n)
        except Exception:  # noqa: BLE001 - Orthanc/Redis временно недоступны — повторим
            logger.exception("Ошибка опроса orthanc-raw")
        finally:
            client.close()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
