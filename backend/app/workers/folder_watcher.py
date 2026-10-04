"""Резервный путь приёма из сетевой папки (ТЗ, FR-1).

Для аппаратов без Storage SCU. Файлы .dcm, попадающие в INGEST_WATCH_DIR,
загружаются в raw-Orthanc, откуда идёт обычный пайплайн обезличивания.

Файл в папке — исходник **с ФИО**. После успешной загрузки он удаляется
(INGEST_DELETE_AFTER_UPLOAD, как RAW_DELETE_AFTER_INGEST для orthanc-raw): раньше
файлы оставались в папке бессрочно. Не загруженный файл остаётся для повтора; периодический
обход подбирает и пропущенные события, и файлы, появившиеся, пока наблюдатель не работал.
Имена файлов в лог не пишутся (в имени бывает ФИО) — только короткий отпечаток.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.core.config import get_settings
from app.services.orthanc import raw_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("folder_watcher")

SWEEP_SECONDS = 60          # периодический обход папки
MIN_AGE_SECONDS = 5         # файл не трогаем, пока он, возможно, дописывается


def _tag(path: Path) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()[:10]


def _is_candidate(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in (".dcm", "") and not path.name.startswith(".")


def _upload(data: bytes) -> None:
    raw = raw_client()
    try:
        raw.upload_dicom(data)
    finally:
        raw.close()


def process_file(path: Path, upload: Callable[[bytes], None], *, delete: bool) -> str:
    """Загрузить файл в приёмник; при успехе — удалить. Возвращает uploaded / failed / skipped."""
    if not _is_candidate(path):
        return "skipped"
    try:
        upload(path.read_bytes())
    except FileNotFoundError:
        return "skipped"                     # уже обработан параллельно (событие и обход)
    except Exception as e:  # noqa: BLE001 - останется в папке, повтор при следующем обходе
        logger.warning("Не удалось загрузить файл %s: %s", _tag(path), type(e).__name__)
        return "failed"
    if delete:
        path.unlink(missing_ok=True)
    logger.info("Загружен из папки: %s%s", _tag(path), ", удалён" if delete else "")
    return "uploaded"


def sweep(root: Path, upload: Callable[[bytes], None], *, delete: bool, now: float | None = None,
          min_age: float = MIN_AGE_SECONDS) -> dict[str, int]:
    """Обойти папку: загрузить всё, что не дописывается. Сводка — для лога."""
    now = time.time() if now is None else now
    out = {"uploaded": 0, "failed": 0, "skipped": 0}
    for path in sorted(root.rglob("*")):
        if not _is_candidate(path):
            continue
        try:
            if now - path.stat().st_mtime < min_age:
                continue
        except FileNotFoundError:
            continue
        out[process_file(path, upload, delete=delete)] += 1
    return out


def leftover_files(root: Path, *, older_than: float, now: float | None = None) -> int:
    """Файлы-исходники, лежащие в папке дольше older_than секунд (для «Состояния системы»)."""
    if not root.is_dir():
        return 0
    now = time.time() if now is None else now
    n = 0
    for path in root.rglob("*"):
        try:
            if _is_candidate(path) and now - path.stat().st_mtime > older_than:
                n += 1
        except FileNotFoundError:
            continue
    return n


class DicomHandler(FileSystemEventHandler):
    def __init__(self, delete: bool) -> None:
        self.delete = delete

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        time.sleep(1.0)  # дать файлу дописаться
        process_file(Path(event.src_path), _upload, delete=self.delete)


def main() -> None:
    settings = get_settings()
    watch_dir = Path(settings.ingest_watch_dir)
    watch_dir.mkdir(parents=True, exist_ok=True)
    delete = settings.ingest_delete_after_upload
    logger.info("Наблюдение за папкой приёма (удаление после загрузки: %s)", delete)

    observer = Observer()
    observer.schedule(DicomHandler(delete), str(watch_dir), recursive=True)
    observer.start()
    try:
        while True:
            res = sweep(watch_dir, _upload, delete=delete)
            if res["uploaded"] or res["failed"]:
                logger.info("Обход папки: %s", res)
            time.sleep(SWEEP_SECONDS)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
