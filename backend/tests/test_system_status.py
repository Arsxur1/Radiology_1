"""Состояние системы: честные проверки вместо «всегда ok» (SR-4)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import system_status as ss
from app.services.system_status import Check, check_backup, check_watcher, run, summarize

OK = ["postgres", "postgres_idmap", "redis", "s3", "orthanc_clean", "orthanc_raw", "watcher", "raw_backlog",
      "disk", "queue", "workers", "models", "backup"]


def _checks(**over):
    out = []
    for n in OK:
        ok, warn = over.get(n, (True, False))
        out.append(Check(n, ok, "x", 1, warn))
    return out


class FakeRedis(dict):
    def get(self, k):
        return super().get(k)


def test_all_ok():
    st = summarize(_checks())
    assert st["status"] == "ok" and st["functions"] == {"viewer": "ok", "ingest": "ok", "ai": "ok"}


def test_ai_failure_does_not_take_down_viewer_or_ingest():
    """Нет действующих моделей — ИИ деградирован, просмотр и приём работают (SR-4)."""
    st = summarize(_checks(models=(True, True)))
    assert st["functions"] == {"viewer": "ok", "ingest": "ok", "ai": "degraded"} and st["status"] == "degraded"


def test_watcher_down_means_ingest_down():
    st = summarize(_checks(watcher=(False, False)))
    assert st["functions"]["ingest"] == "down" and st["functions"]["viewer"] == "ok" and st["status"] == "down"


def test_workers_down_hits_ingest_and_ai():
    st = summarize(_checks(workers=(False, False)))
    assert st["functions"]["ingest"] == "down" and st["functions"]["ai"] == "down"


def test_stale_backup_is_a_warning():
    st = summarize(_checks(backup=(True, True)))
    assert st["status"] == "degraded" and st["functions"]["viewer"] == "ok"


def test_run_never_raises():
    c = run("orthanc_raw", lambda: 1 / 0)
    assert c.ok is False and "ZeroDivisionError" in c.detail


def test_watcher_heartbeat():
    from app.workers.orthanc_watcher import HEARTBEAT_KEY

    assert check_watcher(FakeRedis())[0] is False
    assert check_watcher(FakeRedis({HEARTBEAT_KEY: str(time.time() - 5)}))[0] is True
    stale = check_watcher(FakeRedis({HEARTBEAT_KEY: str(time.time() - 600)}))
    assert stale[0] is False and "остановлен" in stale[1]


def test_backup_age():
    import json

    assert check_backup(FakeRedis())[2] is True                        # нет сведений — предупреждение
    fresh = FakeRedis({ss.BACKUP_KEY: json.dumps({"ts": time.time() - 3600, "size": "38M"})})
    assert check_backup(fresh) == (True, "1 ч назад, 38M", False)
    old = FakeRedis({ss.BACKUP_KEY: json.dumps({"ts": time.time() - 3 * 86400, "size": "38M"})})
    assert check_backup(old)[2] is True


def test_ready_is_public_summary_and_status_is_admin_only(monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    monkeypatch.setattr(ss, "collect", lambda: summarize(_checks(orthanc_clean=(False, False))))
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/ready")
    assert r.status_code == 503 and r.json() == {"status": "down", "viewer": "down", "ingest": "ok", "ai": "ok"}
    assert "checks" not in r.json()                                    # подробности — не публично
    h = {"X-Debug-Subject": "u", "X-Debug-Roles": "radiologist"}
    assert c.get("/system/status", headers=h).status_code == 403
    r = c.get("/system/status", headers={**h, "X-Debug-Roles": "admin"})
    assert r.status_code == 200 and len(r.json()["checks"]) == len(OK)


def test_disk_thresholds():
    from app.services.system_status import disk_state

    gb = 1024**3
    assert disk_state(1000 * gb, 600 * gb) == (True, "свободно 600 ГБ из 1000 ГБ (60%)", False)
    ok, detail, warn = disk_state(1000 * gb, 100 * gb)
    assert ok and warn and "расширять" in detail                     # 10 % — предупреждение
    ok, detail, warn = disk_state(1000 * gb, 30 * gb)
    assert not ok and "остановятся" in detail                         # 3 % — приём под угрозой
    assert disk_state(100 * gb, 8 * gb)[0] is False                    # меньше 10 ГБ — тоже
    st = summarize(_checks(disk=(False, False)))
    assert st["functions"]["ingest"] == "down" and st["functions"]["viewer"] == "ok"


def test_debug_auth_marks_system_down():
    st = summarize(_checks() + [Check("debug_auth", False, "включён")])
    assert st["status"] == "down"


def test_gateway_strips_debug_headers():
    from pathlib import Path

    conf = (Path(__file__).resolve().parents[2] / "infra/nginx/locations.conf.template").read_text(encoding="utf-8")
    api = conf[conf.index("location /api/"):conf.index("}", conf.index("location /api/"))]
    auth = conf[conf.index("location = /_auth"):conf.index("}", conf.index("location = /_auth"))]
    for block in (api, auth):
        assert 'proxy_set_header X-Debug-Subject "";' in block and 'proxy_set_header X-Debug-Roles "";' in block
