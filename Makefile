.PHONY: help up down logs build migrate revision test lint fmt seed backup check-pacs

help:
	@echo "up         — поднять весь стек (docker compose up -d --build)"
	@echo "down       — остановить стек"
	@echo "logs       — логи backend"
	@echo "migrate    — применить миграции БД (alembic upgrade head)"
	@echo "revision   — создать новую миграцию (m=\"описание\")"
	@echo "test       — прогнать тесты backend"
	@echo "lint       — ruff check"
	@echo "fmt        — ruff format"
	@echo "backup     — бэкап PostgreSQL + MinIO"
	@echo "check-pacs — проверить связь с настроенным PACS (.env)"
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
	docker compose exec backend python scripts/init_idmap.py

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

check-pacs:
	bash scripts/check_pacs.sh

seed:
	docker compose exec backend python scripts/seed_demo.py
