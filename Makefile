# Dark Guard AI — Makefile
# ─────────────────────────────────────────────────────────────────────────────
.PHONY: help dev stop build test lint format seed-db install install-browsers

PYTHON   := python3
POETRY   := poetry
DC       := docker-compose
DC_DEV   := docker-compose -f docker-compose.yml -f docker-compose.dev.yml

help:
	@echo ""
	@echo "  Dark Guard AI — Available commands"
	@echo "  ────────────────────────────────────"
	@echo "  make install           Install Python deps via Poetry"
	@echo "  make install-browsers  Install Playwright Chromium"
	@echo "  make dev               Start Redis + Qdrant + backend (hot-reload)"
	@echo "  make stop              Stop all Docker services"
	@echo "  make build             Rebuild all Docker images"
	@echo "  make test              Run pytest suite"
	@echo "  make lint              Run ruff + mypy"
	@echo "  make format            Auto-format with black + ruff"
	@echo "  make seed-db           Seed Qdrant with example dark patterns"
	@echo ""

install:
	$(POETRY) install

install-browsers:
	$(POETRY) run playwright install chromium
	$(POETRY) run playwright install-deps chromium

dev:
	@cp -n .env.example .env || true
	$(DC) up redis qdrant -d
	@echo "Waiting for Redis and Qdrant to be healthy…"
	@sleep 5
	$(POETRY) run uvicorn backend.main:app \
	  --host 0.0.0.0 --port 8000 --reload \
	  --log-level debug

stop:
	$(DC) down

build:
	$(DC) build --no-cache

test:
	$(POETRY) run pytest -v --tb=short

lint:
	$(POETRY) run ruff check .
	$(POETRY) run mypy backend/ agents/ --ignore-missing-imports

format:
	$(POETRY) run black .
	$(POETRY) run ruff check --fix .

seed-db:
	$(POETRY) run python -m vector_store.indexer --seed

# Load extension in Chrome (macOS)
chrome:
	open -a "Google Chrome" --args \
	  --load-extension=$(PWD)/extension \
	  --disable-extensions-except=$(PWD)/extension
