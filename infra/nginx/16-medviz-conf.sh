#!/bin/sh
# Конфигурация шлюза: HTTPS, если в /etc/nginx/tls лежат server.crt и server.key
# (make tls-cert), иначе HTTP — с предупреждением: пароли сотрудников пошли бы по сети
# открытым текстом. Порты: 80/443 — интерфейс, API, вход (/auth), DICOMweb; 3000 — OHIF.
set -eu
TLS=/etc/nginx/tls
LOC=/etc/nginx/medviz-locations.conf
envsubst '${ORTHANC_BASIC_AUTH}' < /etc/nginx/medviz/locations.conf.template > "$LOC"
OUT=/etc/nginx/conf.d/default.conf
# OHIF и Keycloak — через переменные и DNS docker (127.0.0.11): шлюз стартует, даже если
# они временно недоступны; рабочее место, API и снимки от них не зависят (SR-4).
RESOLVER='resolver 127.0.0.11 valid=10s ipv6=off;'
OHIF='location / { set $ohif_upstream http://ohif:80; proxy_pass $ohif_upstream; proxy_set_header Host $host; }'
if [ -s "$TLS/server.crt" ] && [ -s "$TLS/server.key" ]; then
  SSL="ssl_certificate $TLS/server.crt; ssl_certificate_key $TLS/server.key; ssl_protocols TLSv1.2 TLSv1.3;"
  cat > "$OUT" <<CONF
server {
    listen 80;
    server_name _;
    # Сводка готовности — и по HTTP, для внешнего мониторинга без сертификата клиники.
    location = /api/ready { proxy_pass http://backend:8000/ready; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl;
    server_name _;
    $SSL
    $RESOLVER
    include $LOC;
}
server {
    listen 3000 ssl;
    server_name _;
    $SSL
    error_page 497 =301 https://\$host:3000\$request_uri;
    $RESOLVER
    $OHIF
}
CONF
  echo "medviz: шлюз работает по HTTPS" >&2
else
  echo "medviz: ВНИМАНИЕ — нет сертификата ($TLS/server.crt): шлюз по HTTP, пароли идут по сети открыто. Выполните make tls-cert." >&2
  cat > "$OUT" <<CONF
server {
    listen 80;
    server_name _;
    $RESOLVER
    include $LOC;
}
server {
    listen 3000;
    server_name _;
    $RESOLVER
    $OHIF
}
CONF
fi
