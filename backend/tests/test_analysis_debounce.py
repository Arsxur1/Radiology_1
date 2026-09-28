"""Автоанализ стартует один раз — после последнего среза серии."""

from app.workers.analysis_debounce import is_last, schedule


class MemStore:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v):
        self.d[k] = v

    def delete_if(self, k, v):
        if self.d.get(k) == v:
            del self.d[k]
            return True
        return False


def test_only_last_slice_triggers_analysis():
    store, queued = MemStore(), []
    for _ in range(112):                                   # 112 срезов КТ одной серии
        schedule(store, "s1", lambda sid, tok: queued.append((sid, tok)))
    fired = [tok for sid, tok in queued if is_last(store, sid, tok)]
    assert len(queued) == 112 and fired == [queued[-1][1]]
    assert not is_last(store, "s1", queued[-1][1])         # повторно не срабатывает


def test_series_are_independent():
    store, queued = MemStore(), []
    schedule(store, "a", lambda s, t: queued.append((s, t)))
    schedule(store, "b", lambda s, t: queued.append((s, t)))
    assert all(is_last(store, s, t) for s, t in queued)
