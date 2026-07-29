"""Резервный путь приёма из сетевой папки (ТЗ, FR-1).

Для аппаратов без Storage SCU. Файлы .dcm, попадающие в INGEST_WATCH_DIR,
загружаются в raw-Orthanc, откуда идёт обычный пайплайн обезличивания.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.core.config import get_settings
from app.services.orthanc import raw_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("folder_watcher")


class DicomHandler(FileSystemEventHandler):
    def on_created(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in (".dcm", ""):
            return
        # Дать файлу дописаться.
        time.sleep(1.0)
        try:
            data = path.read_bytes()
            raw = raw_client()
            try:
                raw.upload_dicom(data)
                logger.info("Загружен из папки: %s", path.name)
            finally:
                raw.close()
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось загрузить %s", path)


def main() -> None:
    settings = get_settings()
    watch_dir = Path(settings.ingest_watch_dir)
    watch_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Наблюдение за папкой приёма: %s", watch_dir)

    observer = Observer()
    observer.schedule(DicomHandler(), str(watch_dir), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
