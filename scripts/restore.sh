#!/usr/bin/env bash
# Восстановление из бэкапа на чистом сервере (ТЗ, раздел 10). ПЕРЕЗАПИСЫВАЕТ текущие данные.
#   bash scripts/restore.sh backups/20260929-120000 [--yes]
# Порядок: обе БД → объектное хранилище → пересборка обезличенного Orthanc из S3 → веса.
set -euo pipefail

SRC="$(realpath "${1:?укажите каталог бэкапа}")"
KEY="${BACKUP_ENCRYPT_KEY_FILE:-}"

# Сначала — целостность: восстанавливать из повреждённой или незавершённой копии нельзя.
if [ -f "$SRC/SHA256SUMS" ] || [ -f "$SRC/ok" ]; then
  [ -f "$SRC/ok" ] || { echo "Копия $SRC не завершена (нет метки ok) — восстановление отменено" >&2; exit 1; }
else
  echo "Копия старого формата (без контрольных сумм) — целостность не проверить" >&2
fi
if [ -f "$SRC/SHA256SUMS" ]; then
  ( cd "$SRC" && sha256sum --quiet -c SHA256SUMS ) || { echo "Контрольные суммы не сошлись — копия повреждена" >&2; exit 1; }
  echo "Контрольные суммы сошлись"
fi
if { [ -f "$SRC/medviz_idmap.sql.gz.enc" ] || [ -f "$SRC/keycloak.sql.gz.enc" ]; } && [ -z "$KEY" ]; then
  echo "Копия идентифицирующего контура зашифрована: укажите BACKUP_ENCRYPT_KEY_FILE" >&2; exit 1
fi
[ "${2:-}" = "--yes" ] || { read -r -p "Данные будут перезаписаны из $SRC. Продолжить? [yes/N] " a; [ "$a" = "yes" ]; }
S3_SYNC="${S3_SYNC_CMD:-docker compose run --rm -T -v $SRC:/backup backend python scripts/s3_sync.py}"
S3_DIR="${S3_SYNC_CMD:+$SRC/s3}"; S3_DIR="${S3_DIR:-/backup/s3}"
PGU="${POSTGRES_USER:-medviz}"; PGD="${POSTGRES_DB:-medviz}"
IDU="${IDMAP_POSTGRES_USER:-medviz_idmap}"; IDD="${IDMAP_POSTGRES_DB:-medviz_idmap}"

recreate() {  # $1 сервис, $2 пользователь, $3 БД
  docker compose exec -T "$1" psql -q -U "$2" -d postgres -c "DROP DATABASE IF EXISTS \"$3\" WITH (FORCE)"
  docker compose exec -T "$1" psql -q -U "$2" -d postgres -c "CREATE DATABASE \"$3\""
}

echo "→ PostgreSQL (доверенный контур)"
recreate postgres "$PGU" "$PGD"
# Роль аудита (append-only, SR-8) — роли в pg_dump не входят.
docker compose exec -T postgres psql -q -U "$PGU" -d "$PGD" -c \
  "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'medviz_audit') THEN CREATE ROLE medviz_audit LOGIN; END IF; END \$\$;"
gunzip -c "$SRC/medviz.sql.gz" | docker compose exec -T postgres psql -q -v ON_ERROR_STOP=1 -U "$PGU" -d "$PGD" >/dev/null

echo "→ PostgreSQL (идентифицирующий контур)"
recreate postgres-idmap "$IDU" "$IDD"
if [ -f "$SRC/medviz_idmap.sql.gz.enc" ]; then
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$KEY" -in "$SRC/medviz_idmap.sql.gz.enc" | gunzip -c
else
  gunzip -c "$SRC/medviz_idmap.sql.gz"
fi | docker compose exec -T postgres-idmap psql -q -v ON_ERROR_STOP=1 -U "$IDU" -d "$IDD" >/dev/null

if [ -f "$SRC/keycloak.sql.gz.enc" ] || [ -f "$SRC/keycloak.sql.gz" ]; then
  echo "→ PostgreSQL (учётные записи сотрудников, Keycloak)"
  docker compose stop keycloak >/dev/null 2>&1 || true
  recreate postgres-keycloak keycloak keycloak
  if [ -f "$SRC/keycloak.sql.gz.enc" ]; then
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$KEY" -in "$SRC/keycloak.sql.gz.enc" | gunzip -c
  else
    gunzip -c "$SRC/keycloak.sql.gz"
  fi | docker compose exec -T postgres-keycloak psql -q -v ON_ERROR_STOP=1 -U keycloak -d keycloak >/dev/null
  docker compose start keycloak >/dev/null 2>&1 || true
fi

echo "→ Объектное хранилище"
$S3_SYNC restore "$S3_DIR"

echo "→ Просмотрщик: обезличенный Orthanc из S3 (снимки + контуры SEG)"
$S3_SYNC rebuild-viewer

echo "→ Веса моделей"
if [ -d "$SRC/models" ]; then mkdir -p models && cp -r "$SRC/models/." models/; fi

echo "Готово. Проверьте: GET /audit/verify, список исследований, открытие снимка."
