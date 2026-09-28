.PHONY: help up down logs build migrate revision test lint fmt seed backup check-pacs xrv-candidate totalseg-candidate restore

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
