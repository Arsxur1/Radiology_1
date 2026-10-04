"""Папка приёма: исходник с ФИО удаляется после загрузки, имена файлов не попадают в лог."""

from __future__ import annotations

import logging
import os
import time

from app.workers import folder_watcher as fw


def _file(root, name, age=60.0):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"DICM")
    t = time.time() - age
    os.utime(p, (t, t))
    return p


def test_uploaded_file_is_deleted_failed_is_kept_for_retry(tmp_path):
    ok = _file(tmp_path, "Ivanov_Petr.dcm")
    bad = _file(tmp_path, "sub/Sidorova_Anna")            # без расширения — тоже DICOM
    _file(tmp_path, "notes.txt")                          # не DICOM — не трогаем
    fresh = _file(tmp_path, "fresh.dcm", age=0)           # ещё дописывается
    sent = []

    def upload(data, fail=bad):
        if len(sent) == 1:
            raise RuntimeError("приёмник недоступен")
        sent.append(data)

    res = fw.sweep(tmp_path, upload, delete=True)
    assert res == {"uploaded": 1, "failed": 1, "skipped": 0}
    assert not ok.exists() and bad.exists() and fresh.exists()
    assert (tmp_path / "notes.txt").exists()

    # Повторный обход (приёмник поднялся) подбирает оставшийся файл.
    assert fw.sweep(tmp_path, lambda d: None, delete=True)["uploaded"] == 1 and not bad.exists()


def test_delete_can_be_disabled(tmp_path):
    p = _file(tmp_path, "a.dcm")
    assert fw.process_file(p, lambda d: None, delete=False) == "uploaded" and p.exists()


def test_vanished_file_is_skipped(tmp_path):
    assert fw.process_file(tmp_path / "gone.dcm", lambda d: None, delete=True) == "skipped"


def test_file_names_not_logged(tmp_path, caplog):
    p = _file(tmp_path, "Ivanov_Petr_2019.dcm")
    with caplog.at_level(logging.INFO, logger="folder_watcher"):
        fw.process_file(p, lambda d: None, delete=True)
        q = _file(tmp_path, "Sidorova_Anna.dcm")
        fw.process_file(q, lambda d: (_ for _ in ()).throw(OSError("x")), delete=True)
    text = caplog.text
    assert "Ivanov" not in text and "Sidorova" not in text and "Загружен из папки" in text


def test_leftover_counter(tmp_path):
    _file(tmp_path, "old.dcm", age=3600)
    _file(tmp_path, "new.dcm", age=10)
    assert fw.leftover_files(tmp_path, older_than=600) == 1
    assert fw.leftover_files(tmp_path / "missing", older_than=600) == 0
