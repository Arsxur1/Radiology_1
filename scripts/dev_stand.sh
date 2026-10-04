#!/usr/bin/env bash
# Стенд разработки в песочнице: инфраструктура — в контейнерах, backend и интерфейс — на машине.
# НЕ для клиники (там: scripts/init_env.sh → make up). Нужен там, где образ backend не
# собрать (нет доступа к apt внутри сборки), и после пересоздания среды — одной командой.
#
#   scripts/dev_stand.sh          # поднять (идемпотентно: что уже работает — не трогает)
#   scripts/dev_stand.sh stop     # остановить процессы на машине (контейнеры остаются)
#
# Делает: dockerd (если не запущен; убирает оставшиеся pid-файлы) → контейнеры инфраструктуры
# → имена сервисов в /etc/hosts (тот же .env, что и в клинике) → миграции и идентифицирующая
# БД → API :8000, воркер, наблюдатели приёма, интерфейс :4173. Логи — $LOG.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${STAND_LOG:-/tmp/medviz-stand}"
INFRA=(postgres postgres-idmap postgres-keycloak minio orthanc-raw orthanc-clean redis keycloak)
mkdir -p "$LOG"

running() { pgrep -f "$1" >/dev/null 2>&1; }
start() {  # имя, шаблон процесса, команда
  if running "$2"; then echo "  $1 — уже работает"; return; fi
  # В фон уходит только сам процесс (не весь список команд — иначе копия оболочки держит вывод).
  (cd "$ROOT/${4:-backend}"; set -a; . "$ROOT/.env"; set +a; nohup bash -c "$3" >"$LOG/$1.log" 2>&1 </dev/null &)
  echo "  $1 — запущен (лог $LOG/$1.log)"
}

if [ "${1:-}" = "stop" ]; then
  pkill -f '^python3 -m uvicorn app.main' || true
  pkill -f '^python3 -m celery -A app.workers.celery_app worker' || true
  pkill -f '^python3 -m app.workers.(orthanc|folder)_watcher' || true
  pkill -f 'vite preview --port 4173' || true
  echo "процессы стенда остановлены"; exit 0
fi

[ -f "$ROOT/.env" ] || { echo "Нет .env — сначала scripts/init_env.sh (для стенда: ALLOW_DEBUG_AUTH=true)"; exit 1; }

if ! docker info >/dev/null 2>&1; then
  rm -f /var/run/docker.pid /var/run/docker/containerd/containerd.pid
  (dockerd >"$LOG/dockerd.log" 2>&1 &)
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
  docker info >/dev/null 2>&1 || { echo "dockerd не запустился: $LOG/dockerd.log"; exit 1; }
fi

echo "контейнеры: ${INFRA[*]}"
(cd "$ROOT" && docker compose up -d "${INFRA[@]}" >"$LOG/compose.log" 2>&1) || { tail -5 "$LOG/compose.log"; exit 1; }

# Имена сервисов → IP контейнеров (меняются при перезапуске — обновляем каждый раз).
tmp="$(mktemp)"; grep -v "# medviz-stand" /etc/hosts >"$tmp" || true
for s in "${INFRA[@]}"; do
  cid="$(cd "$ROOT" && docker compose ps -q "$s")"
  ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$cid")"
  echo "$ip $s # medviz-stand" >>"$tmp"
done
cat "$tmp" >/etc/hosts; rm -f "$tmp"

for _ in $(seq 1 60); do (cd "$ROOT" && docker compose exec -T postgres pg_isready -q) && break; sleep 1; done
mkdir -p /data/ingest /data/models
(cd "$ROOT/backend" && set -a && . "$ROOT/.env" && set +a && alembic upgrade head >"$LOG/migrate.log" 2>&1 \
  && PYTHONPATH=. python3 scripts/init_idmap.py >>"$LOG/migrate.log" 2>&1) || { tail -5 "$LOG/migrate.log"; exit 1; }
echo "миграции: $(cd "$ROOT/backend" && set -a && . "$ROOT/.env" && set +a && alembic current 2>/dev/null | tail -1)"

start api '^python3 -m uvicorn app.main' 'exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000'
start worker '^python3 -m celery -A app.workers.celery_app worker' \
  'exec python3 -m celery -A app.workers.celery_app worker -l info --concurrency=2'
start orthanc-watcher '^python3 -m app.workers.orthanc_watcher' 'exec python3 -m app.workers.orthanc_watcher'
start folder-watcher '^python3 -m app.workers.folder_watcher' 'exec python3 -m app.workers.folder_watcher'
if [ ! -d "$ROOT/frontend/node_modules" ]; then (cd "$ROOT/frontend" && npm ci >"$LOG/npm.log" 2>&1); fi
if [ ! -d "$ROOT/frontend/dist" ]; then (cd "$ROOT/frontend" && npm run build >"$LOG/build.log" 2>&1); fi
start ui 'vite preview --port 4173' 'exec npx vite preview --port 4173 --strictPort' frontend

for _ in $(seq 1 30); do curl -sf -o /dev/null localhost:8000/health && break; sleep 1; done
echo "API: $(curl -s -o /dev/null -w '%{http_code}' localhost:8000/health)  интерфейс: $(curl -s -o /dev/null -w '%{http_code}' localhost:4173/)"
