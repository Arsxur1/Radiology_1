#!/usr/bin/env bash
# Ежедневный бэкап (ТЗ, раздел 7). PostgreSQL (оба контура) + объекты MinIO.
# Регулярную проверку восстановления делать на чистом стенде (раздел 10).
set -euo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_DIR:-./backups}/${STAMP}"
mkdir -p "$DEST"

echo "→ Бэкап PostgreSQL (доверенный контур)"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-medviz}" "${POSTGRES_DB:-medviz}" \
  | gzip > "$DEST/medviz.sql.gz"

echo "→ Бэкап PostgreSQL (идентифицирующий контур)"
docker compose exec -T postgres-idmap pg_dump -U "${IDMAP_POSTGRES_USER:-medviz_idmap}" \
  "${IDMAP_POSTGRES_DB:-medviz_idmap}" | gzip > "$DEST/medviz_idmap.sql.gz"

echo "→ Бэкап объектов MinIO"
docker compose exec -T minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; mc mirror --overwrite local/ /tmp/minio-backup' || true
docker compose cp minio:/tmp/minio-backup "$DEST/minio" 2>/dev/null || true

echo "Готово: $DEST"
