"""Запуск автоанализа после того, как серия пришла целиком (FR-1 → FR-3).

Срезы КТ/МРТ приходят по одному. Каждый новый срез серии переносит запуск анализа:
в Redis пишется свежая метка, а задача с задержкой выполняется, только если её метка
осталась последней. Так анализ стартует через ANALYSIS_DELAY_SECONDS после последнего
среза — и один раз на серию, а не на первый срез.
"""

from __future__ import annotations

import uuid

KEY = "medviz:analyze:{series_id}"


class RedisStore:  # pragma: no cover - нужен Redis
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url)

    def get(self, key: str) -> str | None:
        v = self._r.get(key)
        return v.decode() if v is not None else None

    def set(self, key: str, value: str) -> None:
        self._r.set(key, value, ex=24 * 3600)

    def delete_if(self, key: str, value: str) -> bool:
        """Атомарно удалить ключ, только если он равен value (иначе — пришёл новый срез)."""
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        return bool(self._r.eval(script, 1, key, value))


def schedule(store, series_id: str, enqueue) -> str:
    """Отметить новый срез и поставить отложенную проверку. enqueue(series_id, token)."""
    token = uuid.uuid4().hex
    store.set(KEY.format(series_id=series_id), token)
    enqueue(series_id, token)
    return token


def is_last(store, series_id: str, token: str) -> bool:
    """True — срезов после этой метки не было: пора анализировать (метка снимается)."""
    return store.delete_if(KEY.format(series_id=series_id), token)
