.PHONY: dev prod migrate-prod dev-worker curl-smoke test test-agent-service lint format

PORT ?= 8000

DATABASE_URL_DEVTEST ?= postgresql+psycopg://postgres:postgres@localhost:5432/gabrr_budget_dev

dev:
	uv run python -m uvicorn app.main:app --reload --port $(PORT) --env-file .env

prod:
	uv run --env-file prod.env python -m uvicorn app.main:app --host 0.0.0.0 --port $(PORT)

migrate-prod:
	uv run --env-file prod.env python -m alembic upgrade head

dev-worker:
	uv run python -m app.workers.import_worker

lint:
	uv run ruff check .

format:
	uv run ruff format .
	uv run ruff check --fix .

# Pytest: all tests under tests/, excluding tests/agents (agent-only docs / live checks — use `make test-agent-service`).
test:
	DATABASE_URL=$(DATABASE_URL_DEVTEST) uv run python -m pytest tests/ -v --ignore=tests/agents; ret=$$?; if [ $$ret -eq 5 ]; then ret=0; fi; exit $$ret

curl-smoke:
	bash scripts/curl_smoke_transactions.sh

test-agent-service:
	bash scripts/test_agent_service/test_agent_service.sh run
