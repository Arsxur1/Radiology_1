"""Приём переживает сбои: повторы с растущей паузой и досылка застрявших снимков (FR-1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.workers import orthanc_watcher as w
from app.workers.tasks import INGEST_MAX_RETRIES, ingest_retry_delay

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _stamp(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y%m%dT%H%M%S")


class FakeRaw:
    def __init__(self, items):
        self.items = items

    def instances_with_reception(self):
        return self.items


def test_retry_window_survives_long_outage():
    delays = [ingest_retry_delay(i) for i in range(INGEST_MAX_RETRIES)]
    assert delays[:4] == [10, 20, 40, 80] and max(delays) == 600
    assert sum(delays) > 40 * 60          # раньше было 3 × 10 с = 30 с


def test_only_old_instances_are_stuck():
    items = [("fresh", _stamp(2)), ("old", _stamp(15)), ("nodate", None), ("bad", "garbage")]
    assert w.stuck_instances(items, NOW) == ["old"]


def test_reconcile_redispatches_and_gives_up_after_limit():
    sent, counts = [], {}

    def counter(iid):
        counts[iid] = counts.get(iid, 0) + 1
        return counts[iid]

    raw = FakeRaw([("a", _stamp(30)), ("b", _stamp(1))])
    for _ in range(w.REDISPATCH_LIMIT):
        assert w.reconcile_once(raw, counter, sent.append, now=NOW) == {"redispatched": 1, "given_up": 0}
    assert sent == ["a"] * w.REDISPATCH_LIMIT                 # свежий «b» не трогаем
    assert w.reconcile_once(raw, counter, sent.append, now=NOW) == {"redispatched": 0, "given_up": 1}
