"""Состояние системы для эксплуатации (SR-4): что работает, что нет и почему.

Каждая проверка — с таймаутом и независимо от остальных: недоступность одного компонента
не мешает проверить другие. Итог сводится к трём функциям платформы:
  - просмотр (viewer): обезличенный Orthanc;
  - приём (ingest): orthanc-raw, наблюдатель журнала, очередь и воркеры, обе БД, S3;
  - ИИ (ai): воркеры и действующие модели. Отказ ИИ не влияет на просмотр и приём.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

WATCHER_STALE_SECONDS = 60          # пульс наблюдателя старше — приём, вероятно, стоит
QUEUE_WARN = 200                    # задач в очереди — предупреждение
BACKUP_STALE_HOURS = 30             # ночной бэкап старше суток с запасом — предупреждение
BACKUP_KEY = "medviz:backup:last"   # пишет scripts/backup.sh по завершении


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    ms: int = 0
    warn: bool = False                # работает, но требует внимания


def run(name: str, fn: Callable[[], tuple[bool, str] | tuple[bool, str, bool]]) -> Check:
    t = time.monotonic()
    try:
        res = fn()
        ok, detail, warn = (res + (False,))[:3]
    except Exception as e:  # noqa: BLE001 - проверка обязана вернуть результат, а не упасть
        ok, detail, warn = False, f"{type(e).__name__}: {str(e)[:160]}", False
    return Check(name, ok, detail, int((time.monotonic() - t) * 1000), warn)


def _redis():
    import redis

    from app.core.config import get_settings

    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)


def check_db(session_factory) -> tuple[bool, str]:
    from sqlalchemy import text

    with session_factory() as s:
        s.execute(text("SELECT 1"))
    return True, "ok"


def check_s3() -> tuple[bool, str]:
    from app.core.config import get_settings
    from app.services.storage import get_minio

    s, c = get_settings(), get_minio()
    missing = [b for b in (s.bucket_images, s.bucket_masks, s.bucket_meshes) if not c.bucket_exists(b)]
    return (not missing, "ok" if not missing else f"нет бакетов: {', '.join(missing)}")


def check_orthanc(factory) -> tuple[bool, str]:
    client = factory()
    try:
        r = client._client.get("/statistics", timeout=3)
        r.raise_for_status()
        d = r.json()
        return True, f"{d.get('CountStudies', 0)} исследований, {d.get('CountInstances', 0)} снимков"
    finally:
        client.close()


DISK_WARN = (0.15, 50)    # доля свободного места / ГБ — предупреждение
DISK_DOWN = (0.05, 10)    # ниже — приём и базы вот-вот остановятся


def disk_state(total: int, free: int) -> tuple[bool, str, bool]:
    gb, frac = free / 1024**3, free / total if total else 0.0
    detail = f"свободно {gb:.0f} ГБ из {total / 1024**3:.0f} ГБ ({frac:.0%})"
    if frac < DISK_DOWN[0] or gb < DISK_DOWN[1]:
        return False, detail + " — места почти нет: приём, базы и бэкап остановятся", False
    if frac < DISK_WARN[0] or gb < DISK_WARN[1]:
        return True, detail + " — пора расширять диск или переносить архив", True
    return True, detail, False


def check_disk() -> tuple[bool, str, bool]:
    """Диск с данными: тома docker (снимки, базы, S3) лежат на одном диске с томом приёма."""
    import shutil

    from app.core.config import get_settings

    u = shutil.disk_usage(get_settings().ingest_watch_dir)
    return disk_state(u.total, u.free)


def check_debug_auth() -> tuple[bool, str]:
    """Отладочный вход (любая роль по заголовку) в рабочей системе — недопустим."""
    from app.core.config import get_settings

    if get_settings().allow_debug_auth:
        return False, ("ALLOW_DEBUG_AUTH=true: вход по заголовку без пароля включён — выключите в .env "
                       "(через шлюз он заблокирован, но API на самом сервере открыт)")
    return True, "выключен"


def check_pseudonym_key() -> tuple[bool, str]:
    """Ключ псевдонимизации задан и не учебный — без него приём остановлен (SR-9)."""
    from app.core.pseudonym import key_state

    return key_state()


def check_raw_backlog() -> tuple[bool, str, bool]:
    """Снимки, застрявшие в orthanc-raw: исходники с ФИО, не дошедшие до врача."""
    from datetime import UTC, datetime

    from app.services.orthanc import raw_client
    from app.workers.orthanc_watcher import stuck_instances

    client = raw_client()
    try:
        stuck = stuck_instances(client.instances_with_reception(), datetime.now(UTC))
    finally:
        client.close()
    if stuck:
        return True, f"не обработано {len(stuck)} снимков старше 10 мин — досылаются автоматически", True
    return True, "нет", False


def check_watcher(r) -> tuple[bool, str, bool] | tuple[bool, str]:
    from app.workers.orthanc_watcher import HEARTBEAT_KEY

    v = r.get(HEARTBEAT_KEY)
    if v is None:
        return False, "нет пульса: наблюдатель orthanc-raw не запущен — новые снимки не принимаются"
    age = time.time() - float(v)
    if age > WATCHER_STALE_SECONDS:
        return False, f"последний успешный опрос {int(age)} с назад — приём снимков остановлен"
    return True, f"опрос {int(age)} с назад"


def check_queue(r) -> tuple[bool, str, bool]:
    import redis

    from app.core.config import get_settings

    broker = redis.Redis.from_url(get_settings().celery_broker_url, socket_timeout=2)
    n = int(broker.llen("celery"))
    return True, f"в очереди {n}", n > QUEUE_WARN


def check_workers() -> tuple[bool, str]:
    from app.workers.celery_app import celery_app

    replies = celery_app.control.ping(timeout=1.5) or []
    return (bool(replies), f"отвечают: {len(replies)}" if replies else "ни один воркер не отвечает — анализ стоит")


def check_backup(r) -> tuple[bool, str, bool]:
    import json

    v = r.get(BACKUP_KEY)
    if v is None:
        return True, "сведений о бэкапе нет (make backup-install)", True
    d = json.loads(v)
    age_h = (time.time() - float(d["ts"])) / 3600
    return True, f"{age_h:.0f} ч назад, {d.get('size', '?')}", age_h > BACKUP_STALE_HOURS


def check_models(db_factory) -> tuple[bool, str, bool]:
    from sqlalchemy import func, select

    from app.models.ml import ModelStatus, ModelVersion

    with db_factory() as s:
        rows = s.execute(select(ModelVersion.task, func.count()).where(ModelVersion.status == ModelStatus.ACTIVE)
                         .group_by(ModelVersion.task)).all()
    active = {t: n for t, n in rows}
    detail = ", ".join(f"{t}: {n}" for t, n in sorted(active.items())) or "действующих моделей нет"
    return True, detail, not active


def check_incidents(db_factory) -> tuple[bool, str, bool]:
    """Открытые серьёзные инциденты (вред пациенту возможен) — требуют срочного разбора."""
    from app.services.incidents import summary

    with db_factory() as s:
        sm = summary(s)
    if not sm["total"]:
        return True, "сообщений нет", False
    return True, f"открыто {sm['open']}, из них серьёзных {sm['open_serious']}", sm["open_serious"] > 0


def check_patient_links(db_factory) -> tuple[bool, str, bool]:
    """Пациенты, ждущие ручного сопоставления (неоднозначный номер карты при приёме)."""
    from app.services.patient_admin import link_review_queue

    with db_factory() as s:
        n = len(link_review_queue(s))
    return True, (f"ждут сопоставления: {n}" if n else "все сопоставлены"), n > 0


def collect() -> dict:
    from app.db.session import IdMapSessionLocal, SessionLocal
    from app.services.orthanc import clean_client, raw_client

    r = _redis()
    checks = [
        run("postgres", lambda: check_db(SessionLocal)),
        run("postgres_idmap", lambda: check_db(IdMapSessionLocal)),
        run("redis", lambda: (bool(r.ping()), "ok")),
        run("s3", check_s3),
        run("orthanc_clean", lambda: check_orthanc(clean_client)),
        run("orthanc_raw", lambda: check_orthanc(raw_client)),
        run("watcher", lambda: check_watcher(r)),
        run("raw_backlog", check_raw_backlog),
        run("debug_auth", check_debug_auth),
        run("pseudonym_key", check_pseudonym_key),
        run("disk", check_disk),
        run("queue", lambda: check_queue(r)),
        run("workers", check_workers),
        run("models", lambda: check_models(SessionLocal)),
        run("backup", lambda: check_backup(r)),
        run("incidents", lambda: check_incidents(SessionLocal)),
        run("patient_links", lambda: check_patient_links(SessionLocal)),
    ]
    return summarize(checks)


def summarize(checks: list[Check]) -> dict:
    by = {c.name: c for c in checks}

    def state(names: list[str]) -> str:
        items = [by[n] for n in names if n in by]
        if any(not c.ok for c in items):
            return "down"
        return "degraded" if any(c.warn for c in items) else "ok"

    functions = {
        "viewer": state(["orthanc_clean"]),
        "ingest": state(["orthanc_raw", "watcher", "raw_backlog", "queue", "workers", "postgres", "postgres_idmap",
                         "redis", "s3", "disk", "pseudonym_key"]),
        "ai": state(["workers", "models", "s3"]),
    }
    if not by.get("debug_auth", Check("", True, "")).ok:
        return {"status": "down", "functions": functions, "checks": [asdict(c) for c in checks],
                "checked_at": time.time()}
    overall = "down" if "down" in (functions["viewer"], functions["ingest"]) else \
        "degraded" if any(v != "ok" for v in functions.values()) \
        or any(by.get(n, Check("", True, "")).warn for n in ("backup", "incidents", "patient_links")) \
        else "ok"
    return {"status": overall, "functions": functions, "checks": [asdict(c) for c in checks],
            "checked_at": time.time()}
