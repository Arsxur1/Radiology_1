#!/usr/bin/env bash
# Проверка связи с настроенным PACS (ТЗ, FR-1).
#
# Использует узел PACS из .env (PACS_AET/PACS_HOST/PACS_PORT). Запускать после
# заполнения параметров:  bash scripts/check_pacs.sh
#
# Требует запущенный backend (make up) и, для классического DICOM, зависимость
# коннектора:  docker compose exec backend pip install -e '.[pacs]'
set -euo pipefail

BACKEND="${BACKEND_URL:-http://localhost:8000}"
# Отладочная авторизация админом (только при ALLOW_DEBUG_AUTH=true на стенде).
AUTH=(-H "X-Debug-Subject: admin" -H "X-Debug-Roles: admin")

echo "→ Текущая конфигурация PACS:"
curl -sS "${AUTH[@]}" "$BACKEND/pacs/config" || true
echo

echo "→ C-ECHO к настроенному узлу PACS:"
curl -sS -X POST "${AUTH[@]}" "$BACKEND/pacs/echo/default"
echo

echo "Готово. Если C-ECHO неуспешен — проверьте PACS_HOST/PACS_PORT/PACS_AET в .env"
echo "и что наш AE (PACS_LOCAL_AET) прописан в самом PACS как разрешённый узел."
