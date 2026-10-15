# MolDock Studio — developer entry points
#
# Everything is intentionally tiny so a new contributor can read it in one go.
# See README.md for the full walkthrough and docs/troubleshooting.md for help.

SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
PY := .venv/bin/python
UVICORN := .venv/bin/uvicorn
PYTEST := .venv/bin/pytest

.PHONY: help setup backend-setup frontend-setup dev dev-backend dev-frontend \
        test test-backend test-frontend test-e2e lint build up down logs clean \
        native-check data

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: backend-setup frontend-setup ## Install backend (uv) and frontend (npm) dependencies

backend-setup: ## Create backend/.venv and install pinned dependencies
	cd $(BACKEND) && uv sync --extra dev

frontend-setup: ## Install frontend dependencies
	cd $(FRONTEND) && npm install

dev: ## Run backend and frontend dev servers together
	@echo "backend  -> http://127.0.0.1:8000/docs"
	@echo "frontend -> http://127.0.0.1:5173"
	@trap 'kill 0' INT TERM; \
	( cd $(BACKEND) && .venv/bin/uvicorn app.main:app --reload --port 8000 ) & \
	( cd $(FRONTEND) && npm run dev ) & \
	wait

dev-backend: ## Run the FastAPI dev server only
	cd $(BACKEND) && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run the Vite dev server only
	cd $(FRONTEND) && npm run dev

native-check: ## Report which scientific tools this machine can run
	cd $(BACKEND) && .venv/bin/python -m app.cli capabilities

test: test-backend test-frontend ## Run the full test suite

test-backend: ## Run backend unit + API tests
	cd $(BACKEND) && .venv/bin/pytest $(ARGS)

test-frontend: ## Type-check the frontend and run vitest unit tests
	cd $(FRONTEND) && npm run typecheck && npm run test

test-e2e: ## Run the Playwright end-to-end acceptance test (Phase 1)
	cd $(FRONTEND) && npm run test:e2e

lint: ## Lint backend (ruff) and frontend (tsc)
	cd $(BACKEND) && .venv/bin/ruff check app tests
	cd $(FRONTEND) && npm run typecheck

build: ## Production build of the frontend
	cd $(FRONTEND) && npm run build

up: ## Start the containerised stack (backend). See README for platform notes.
	docker compose up --build -d
	@docker compose ps

down: ## Stop the containerised stack
	docker compose down

logs: ## Tail container logs
	docker compose logs -f --tail=100

data: ## (Re)download redistributable test structures into backend/app/data/
	cd $(BACKEND) && .venv/bin/python -m app.cli fetch-test-data

clean: ## Remove caches and build output (keeps .venv and node_modules)
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache $(FRONTEND)/dist \
		$(FRONTEND)/.vite $(FRONTEND)/node_modules/.vite
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
