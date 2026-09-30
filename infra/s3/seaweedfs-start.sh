#!/bin/sh
# S3-хранилище платформы на SeaweedFS (Apache-2.0).
# Почему не MinIO: образ minio/minio на Docker Hub больше не публикуется (проверено:
# «repository does not exist»). Клиникам со своим MinIO — docker-compose.minio.yml.
#
# Доступ — только по ключам MINIO_ROOT_USER / MINIO_ROOT_PASSWORD из .env (анонимный
# доступ SeaweedFS по умолчанию разрешён — здесь он закрыт конфигом identities).
# Тома по 1 ГБ: с размером по умолчанию (30 ГБ) на диске с меньшим свободным местом
# SeaweedFS не создаёт ни одного тома и отвечает 500 на запись (проверено на стенде).
set -eu
: "${S3_ACCESS_KEY:?задайте MINIO_ROOT_USER в .env}"
: "${S3_SECRET_KEY:?задайте MINIO_ROOT_PASSWORD в .env}"
umask 077
cat > /tmp/s3.json <<JSON
{"identities": [{"name": "medviz",
  "credentials": [{"accessKey": "${S3_ACCESS_KEY}", "secretKey": "${S3_SECRET_KEY}"}],
  "actions": ["Admin", "Read", "List", "Tagging", "Write"]}]}
JSON
exec weed server -dir=/data -s3 -s3.port=9000 -s3.config=/tmp/s3.json \
  -master.volumeSizeLimitMB=1024 -volume.max=0
