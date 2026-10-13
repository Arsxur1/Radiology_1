#!/usr/bin/env bash
# Эмулятор H-PACS для стенда разработки (НЕ для клиники): Orthanc с AE HIPACS в сети стенда.
# Знает узел платформы MEDVIZ_RAW (orthanc-raw:4242) как адресат C-STORE/C-MOVE, разрешает
# C-ECHO/C-FIND/C-MOVE и приём заключений SR — как должен быть настроен настоящий H-PACS
# (docs/PACS-NCMC.md). После запуска в .env стенда: PACS_AET=HIPACS PACS_HOST=hpacs PACS_PORT=4242.
#
#   scripts/dev_hpacs.sh          # поднять (идемпотентно); ответы в UTF-8, как у настроенного PACS
#   HPACS_ENCODING=Latin1 scripts/dev_hpacs.sh   # как ненастроенный: кириллица в C-FIND теряется
#   scripts/dev_hpacs.sh rm       # удалить вместе с данными
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME=medviz-hpacs
NET="$(cd "$ROOT" && docker compose ps -q orthanc-raw | xargs docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')"

if [ "${1:-}" = "rm" ]; then docker rm -f "$NAME" >/dev/null 2>&1 || true; echo "эмулятор удалён"; exit 0; fi

if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" --network "$NET" \
    -e ORTHANC__NAME=HIPACS-emulator \
    -e ORTHANC__DICOM_AET=HIPACS \
    -e ORTHANC__DICOM_PORT=4242 \
    -e ORTHANC__DEFAULT_ENCODING="${HPACS_ENCODING:-Utf8}" \
    -e ORTHANC__AUTHENTICATION_ENABLED=false \
    -e ORTHANC__DICOM_ALWAYS_ALLOW_ECHO=true \
    -e ORTHANC__DICOM_ALWAYS_ALLOW_FIND=true \
    -e ORTHANC__DICOM_ALWAYS_ALLOW_MOVE=true \
    -e ORTHANC__DICOM_ALWAYS_ALLOW_STORE=true \
    -e 'ORTHANC__DICOM_MODALITIES={"MEDVIZ_RAW": ["MEDVIZ_RAW", "orthanc-raw", 4242]}' \
    orthancteam/orthanc:latest >/dev/null
fi
ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$NAME")"
tmp="$(mktemp)"; grep -v "# medviz-hpacs" /etc/hosts >"$tmp" || true
echo "$ip hpacs # medviz-hpacs" >>"$tmp"; cat "$tmp" >/etc/hosts; rm -f "$tmp"
for _ in $(seq 1 30); do curl -sf -o /dev/null http://hpacs:8042/system && break; sleep 1; done
echo "H-PACS (эмулятор): AE HIPACS, DICOM hpacs:4242, REST http://hpacs:8042 — $(curl -s -o /dev/null -w '%{http_code}' http://hpacs:8042/system)"
