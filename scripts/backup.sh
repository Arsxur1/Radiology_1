#!/usr/bin/env bash
# Ежедневный бэкап (ТЗ, раздел 7): PostgreSQL (оба контура) + объектное хранилище + веса.
# Восстановление: scripts/restore.sh <каталог>. Проверять восстановление регулярно (раздел 10).
#
# Переменные:
#   BACKUP_DIR               куда складывать (по умолчанию ./backups)
#   BACKUP_KEEP              сколько последних копий хранить (по умолчанию 14; 0 — не удалять)
#   BACKUP_ENCRYPT_KEY_FILE  файл с ключом: дамп идентифицирующего контура (ФИО, номера карт)
#                            шифруется AES-256 и НИКОГДА не пишется на диск открытым текстом.
#                            Ключ хранить отдельно от копий (иначе шифрование бессмысленно).
# Расписание — systemd-таймер infra/backup/ (make backup-install), каждую ночь.
set -euo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
ROOT="$(realpath -m "${BACKUP_DIR:-./backups}")"
DEST="$ROOT/${STAMP}"
KEEP="${BACKUP_KEEP:-14}"
KEY="${BACKUP_ENCRYPT_KEY_FILE:-}"
if [ -n "$KEY" ] && [ ! -r "$KEY" ]; then echo "Нет доступа к ключу шифрования $KEY" >&2; exit 1; fi
mkdir -p "$DEST"
# Незавершённая копия не должна выглядеть готовой: метка «ok» ставится последней.
trap 'echo "Бэкап НЕ завершён: $DEST" >&2' ERR
# Команда запуска Python-утилит платформы (переопределяется на стендах без образа backend).
S3_SYNC="${S3_SYNC_CMD:-docker compose run --rm -T -v $DEST:/backup backend python scripts/s3_sync.py}"
S3_DIR="${S3_SYNC_CMD:+$DEST/s3}"; S3_DIR="${S3_DIR:-/backup/s3}"

echo "→ PostgreSQL (доверенный контур)"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-medviz}" "${POSTGRES_DB:-medviz}" \
  | gzip > "$DEST/medviz.sql.gz"

echo "→ PostgreSQL (идентифицирующий контур)"
dump_idmap() {
  docker compose exec -T postgres-idmap pg_dump -U "${IDMAP_POSTGRES_USER:-medviz_idmap}" \
    "${IDMAP_POSTGRES_DB:-medviz_idmap}" | gzip
}
if [ -n "$KEY" ]; then
  dump_idmap | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$KEY" \
    > "$DEST/medviz_idmap.sql.gz.enc"
else
  echo "  ВНИМАНИЕ: BACKUP_ENCRYPT_KEY_FILE не задан — ФИО и номера карт в копии не зашифрованы" >&2
  dump_idmap > "$DEST/medviz_idmap.sql.gz"
fi

echo "→ Объектное хранилище (снимки, маски, контуры SEG)"
$S3_SYNC dump "$S3_DIR"

echo "→ Веса моделей (models/)"
if [ -d models ]; then cp -r models "$DEST/models"; fi

echo "→ Контрольные суммы"
( cd "$DEST" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
date -Iseconds > "$DEST/ok"

if [ "$KEEP" -gt 0 ]; then
  echo "→ Храним последние $KEEP копий"
  # Удаляются только завершённые копии старше последних KEEP; незавершённые не трогаем.
  ls -1d "$ROOT"/[0-9]*-[0-9]* 2>/dev/null | while read -r d; do [ -f "$d/ok" ] && echo "$d"; done \
    | sort | head -n "-$KEEP" | while read -r old; do echo "  удаляю $old"; rm -rf -- "$old"; done
fi
ln -sfn "$DEST" "$ROOT/latest"
SIZE="$(du -sh "$DEST" | cut -f1)"
# Отметка для панели «Состояние системы» (без путей к данным пациентов — только время и размер).
docker compose exec -T redis redis-cli SET medviz:backup:last \
  "{\"ts\": $(date +%s), \"size\": \"$SIZE\", \"stamp\": \"$STAMP\"}" >/dev/null 2>&1 \
  || echo "  (отметка о бэкапе в Redis не записана — панель состояния её не увидит)" >&2
echo "Готово: $DEST ($SIZE)"
