#!/usr/bin/env bash
# Создать .env для установки: из .env.example, каждая заглушка change_me_* → случайный секрет.
#
#   scripts/init_env.sh            # создаёт .env рядом с docker-compose.yml
#   scripts/init_env.sh path/.env  # в другое место (стенд, проверка)
#
# Существующий файл не перезаписывается: в нём ключ псевдонимизации, без которого новые
# исследования не свяжутся с прошлыми. Секреты на экран не выводятся. Адреса (PACS, сервер)
# и прочие настройки — по-прежнему вручную по комментариям в файле.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/.env}"
if [ -e "$OUT" ]; then
  echo "Файл $OUT уже есть — не перезаписываю (в нём ключи площадки)." >&2
  exit 1
fi
umask 077
n=0
while IFS= read -r line || [ -n "$line" ]; do
  if [[ "$line" =~ ^([A-Z0-9_]+)=change_me[A-Za-z0-9_]*(.*)$ ]]; then
    printf '%s=%s%s\n' "${BASH_REMATCH[1]}" "$(openssl rand -hex 32)" "${BASH_REMATCH[2]}"
    n=$((n + 1))
  else
    printf '%s\n' "$line"
  fi
done < "$ROOT/.env.example" > "$OUT"
if grep -q "change_me" "$OUT"; then
  echo "Остались заглушки change_me — проверьте $OUT" >&2
  exit 1
fi
echo "Создан $OUT (права 600): сгенерировано секретов — $n. Копию PSEUDONYM_KEY сохраните"
echo "отдельно от сервера (без него новые исследования не свяжутся с прошлыми)."
