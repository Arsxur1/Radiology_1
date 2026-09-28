"""Наблюдатель orthanc-raw: журнал изменений → очередь обезличивания (FR-1)."""

from app.workers.orthanc_watcher import poll_once


class FakeOrthanc:
    def __init__(self, changes):
        self.changes = changes  # [(seq, type, id)]

    def get_changes(self, since=0, limit=100):
        page = [c for c in self.changes if c[0] > since][:limit]
        last = page[-1][0] if page else since
        return {
            "Changes": [{"Seq": s, "ChangeType": t, "ID": i} for s, t, i in page],
            "Last": last,
            "Done": last >= (self.changes[-1][0] if self.changes else 0),
        }


class MemCursor:
    def __init__(self):
        self.value = 0

    def get(self):
        return self.value

    def set(self, v):
        self.value = v


def test_dispatches_new_instances_across_pages_and_resumes():
    changes = [(1, "NewPatient", "p"), (2, "NewInstance", "i1"), (3, "NewSeries", "s"),
               (4, "NewInstance", "i2"), (5, "StableSeries", "s"), (6, "NewInstance", "i3")]
    orthanc, cursor, sent = FakeOrthanc(changes), MemCursor(), []
    assert poll_once(orthanc, cursor, sent.append, limit=2) == 3
    assert sent == ["i1", "i2", "i3"] and cursor.value == 6
    assert poll_once(orthanc, cursor, sent.append) == 0          # повторно не отправляет
    orthanc.changes.append((7, "NewInstance", "i4"))
    assert poll_once(orthanc, cursor, sent.append) == 1 and sent[-1] == "i4"


def test_cursor_not_advanced_when_dispatch_fails():
    orthanc, cursor = FakeOrthanc([(1, "NewInstance", "i1")]), MemCursor()

    def boom(_):
        raise RuntimeError("очередь недоступна")

    try:
        poll_once(orthanc, cursor, boom)
    except RuntimeError:
        pass
    assert cursor.value == 0                                      # снимок не потерян


def test_raw_source_dropped_after_ingest_only_when_enabled():
    from app.workers.tasks import _drop_raw

    class Raw:
        def __init__(self, fail=False):
            self.deleted, self.fail = [], fail

        def delete_instance(self, iid):
            if self.fail:
                raise RuntimeError("orthanc недоступен")
            self.deleted.append(iid)

    r = Raw()
    assert _drop_raw(r, "i1", True) and r.deleted == ["i1"]
    assert not _drop_raw(r, "i2", False) and r.deleted == ["i1"]
    assert not _drop_raw(Raw(fail=True), "i3", True)          # ошибка удаления не ломает приём
