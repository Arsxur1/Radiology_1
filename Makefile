.PHONY: help up down logs build migrate revision test lint fmt seed backup backup-install tls-cert check-pacs xrv-candidate totalseg-candidate restore keycloak-configure

help:
	@echo "up         — поднять весь стек (docker compose up -d --build)"
	@echo "down       — остановить стек"
	@echo "logs       — логи backend"
	@echo "migrate    — применить миграции БД (alembic upgrade head)"
	@echo "revision   — создать новую миграцию (m=\"описание\")"
	@echo "test       — прогнать тесты backend"
	@echo "lint       — ruff check"
	@echo "fmt        — ruff format"
	@echo "backup     — бэкап PostgreSQL (оба контура) + S3 + веса моделей"
	@echo "backup-install — ночной бэкап по расписанию (systemd), ключ шифрования /etc/medviz/backup.key"
	@echo "keycloak-configure — адрес сервера в клиенты входа Keycloak (после установки/смены IP)"
	@echo "tls-cert   — центр сертификации клиники и сертификат шлюза: make tls-cert HOST=<IP>"
	@echo "restore    — восстановление: make restore BACKUP=backups/<дата-время>"
	@echo "check-pacs — проверить связь с настроенным PACS (.env)"
	@echo "totalseg-candidate — кандидат сегментации КТ на TotalSegmentator (без GPU, быстрый режим)"
	@echo "xrv-candidate — кандидат из открытой модели для теневого прогона (без GPU)"
	@echo "seed       — загрузить демо-данные для показа (без PACS/GPU)"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f backend worker

build:
	docker compose build

migrate:
	docker compose exec backend alembic upgrade head
	docker compose exec -e PYTHONPATH=/app backend python scripts/init_idmap.py

revision:
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check .

fmt:
	cd backend && ruff format .

backup:
	bash scripts/backup.sh

# Ночной бэкап по расписанию (root). BACKUP_DIR — лучше отдельный диск.
BACKUP_DIR ?= $(CURDIR)/backups
backup-install:
	@test "$$(id -u)" = 0 || { echo "Нужен root (sudo make backup-install)"; exit 1; }
	install -d -m 700 /etc/medviz
	@test -f /etc/medviz/backup.key || { umask 077; openssl rand -base64 48 > /etc/medviz/backup.key; \
	  echo "Создан ключ /etc/medviz/backup.key — СКОПИРУЙТЕ его в сейф: без него копию ФИО не восстановить"; }
	sed -e 's#__MEDVIZ_DIR__#$(CURDIR)#g' -e 's#__BACKUP_DIR__#$(BACKUP_DIR)#g' \
	  infra/backup/medviz-backup.service > /etc/systemd/system/medviz-backup.service
	install -m 644 infra/backup/medviz-backup.timer /etc/systemd/system/medviz-backup.timer
	systemctl daemon-reload && systemctl enable --now medviz-backup.timer
	systemctl list-timers medviz-backup.timer

# Восстановление: make restore BACKUP=backups/<дата-время>  (перезаписывает данные!)
restore:
	bash scripts/restore.sh $(BACKUP)

check-pacs:
	bash scripts/check_pacs.sh

seed:
	docker compose exec -e PYTHONPATH=/app backend python scripts/seed_demo.py --with-storage

# Кандидат из открытой модели TorchXRayVision для теневого прогона (нужен WORKER_EXTRAS=[infer]).
# Веса и registration.json кладутся в ./models; регистрация — в админке (→ SHADOW).
xrv-candidate:
	docker compose run --rm -v $(PWD)/models:/data/models-rw -e PYTHONPATH=/app worker \
		python scripts/xrv_candidate.py --weights $${XRV_WEIGHTS:-densenet121-res224-all} --out /data/models-rw

# Кандидат сегментации КТ (TotalSegmentator, задача total). Веса — в кэше воркера,
# их отпечаток сверяется при каждом запуске. registration.json → ./models → админка.
totalseg-candidate:
	docker compose run --rm -v $(PWD)/models:/data/models-rw -v totalseg_weights:/root/.totalsegmentator \
		-e PYTHONPATH=/app worker python scripts/totalseg_candidate.py --out /data/models-rw

# Прописать адрес сервера (KEYCLOAK_PUBLIC_URL из .env) в клиенты входа Keycloak.
keycloak-configure:
	docker compose run --rm -e PYTHONPATH=/app backend python scripts/keycloak_configure.py

# HTTPS для шлюза: центр сертификации клиники (создаётся один раз) + сертификат сервера.
# ca.crt — на рабочие места врачей (доверенные корневые центры); ca.key — в сейф.
TLS_DIR := infra/tls
tls-cert:
	@test -n "$(HOST)" || { echo "Укажите адрес сервера: make tls-cert HOST=10.0.0.50"; exit 1; }
	@umask 077; test -f $(TLS_DIR)/ca.key || { \
	  openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes -keyout $(TLS_DIR)/ca.key \
	    -out $(TLS_DIR)/ca.crt -subj "/CN=medviz clinic CA" \
	    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1; \
	  echo "Создан центр сертификации $(TLS_DIR)/ca.crt — установите его на рабочие места врачей"; }
	@umask 077; SAN=$$(echo "$(HOST)" | grep -Eq '^[0-9.]+$$' && echo "IP:$(HOST)" || echo "DNS:$(HOST)"); \
	  openssl req -newkey rsa:2048 -nodes -keyout $(TLS_DIR)/server.key -out $(TLS_DIR)/server.csr \
	    -subj "/CN=$(HOST)" >/dev/null 2>&1 && \
	  printf "subjectAltName=$$SAN\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment\n" > $(TLS_DIR)/server.ext && \
	  openssl x509 -req -in $(TLS_DIR)/server.csr -CA $(TLS_DIR)/ca.crt -CAkey $(TLS_DIR)/ca.key \
	    -CAcreateserial -days 825 -sha256 -extfile $(TLS_DIR)/server.ext -out $(TLS_DIR)/server.crt >/dev/null 2>&1 && \
	  rm -f $(TLS_DIR)/server.csr $(TLS_DIR)/server.ext && chmod 644 $(TLS_DIR)/server.crt $(TLS_DIR)/ca.crt && \
	  echo "Сертификат шлюза для $(HOST): $(TLS_DIR)/server.crt (825 дней). Перезапустите шлюз: docker compose restart web"
