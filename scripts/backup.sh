#!/usr/bin/env bash
# Ежедневный бэкап (ТЗ, раздел 7): PostgreSQL (оба контура) + объектное хранилище + веса.
# Восстановление: scripts/restore.sh <каталог>. Проверять восстановление регулярно (раздел 10).
set -euo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$(realpath -m "${BACKUP_DIR:-./backups}/${STAMP}")"
mkdir -p "$DEST"
# Команда запуска Python-утилит платформы (переопределяется на стендах без образа backend).
S3_SYNC="${S3_SYNC_CMD:-docker compose run --rm -T -v $DEST:/backup backend python scripts/s3_sync.py}"
S3_DIR="${S3_SYNC_CMD:+$DEST/s3}"; S3_DIR="${S3_DIR:-/backup/s3}"

echo "→ PostgreSQL (доверенный контур)"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-medviz}" "${POSTGRES_DB:-medviz}" \
  | gzip > "$DEST/medviz.sql.gz"

echo "→ PostgreSQL (идентифицирующий контур)"
docker compose exec -T postgres-idmap pg_dump -U "${IDMAP_POSTGRES_USER:-medviz_idmap}" \
  "${IDMAP_POSTGRES_DB:-medviz_idmap}" | gzip > "$DEST/medviz_idmap.sql.gz"

echo "→ Объектное хранилище (снимки, маски, контуры SEG)"
$S3_SYNC dump "$S3_DIR"

echo "→ Веса моделей (models/)"
if [ -d models ]; then cp -r models "$DEST/models"; fi

echo "Готово: $DEST"
