# Gabrr Budget API

Parse financial documents (CSV/PDF) into normalized transactions using AI agents. Upload a file, choose a model, and receive clean, structured transaction data.

## System Requirements

- Python 3.11+
- `uv` package manager (recommended)
- OpenRouter API key
- PDF parsing uses Docling; if PDF parsing fails due to system libs, see Docling install notes

## Quick Start

```bash
# Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Configure environment (database URL, ADK URL, defaults)
cp .env.example .env

# Run database migrations (Postgres must be up)
uv run alembic upgrade head

# Run the API
make dev

# Run workers
make dev-worker
```

## Local development

The API and background workers are separate processes. For the **PDF import job** flow (`POST /agents/process-file`, SSE on `GET /import-jobs/{id}/events`), run all of the following:


| Terminal         | Command                              | Port / role                                                      |
| ---------------- | ------------------------------------ | ---------------------------------------------------------------- |
| agent-normalizer | `cd ../agent-normalizer && make api` | **8001** — ADK REST API the backend calls via Agent Gateway      |
| backend API      | `make dev`                           | **8000** — FastAPI (`uvicorn`, reload)                           |
| import worker    | `make dev-worker`                    | — polls `import_jobs`, calls the agent, saves draft transactions |
| frontend         | `cd ../frontend && npm run dev`      | **3000** — test UI at `/import`                                  |


`**make dev`** — starts the HTTP API:

```bash
make dev   # uvicorn on PORT (default 8000), loads .env
```

`**make dev-worker**` — starts the import job worker (`app.workers.import_worker`):

```bash
make dev-worker
# or process a single job and exit:
uv run python -m app.workers.import_worker --once
# optional stable id when running multiple workers:
uv run python -m app.workers.import_worker --worker-id my-worker-1
```

The worker claims `pending` jobs, invokes the configured Agent Gateway (Google ADK provider → **agent-normalizer** at `ADK_BASE_URL`, default `http://127.0.0.1:8001`), writes agent input/output on the job row, and inserts transactions with `is_draft=true`. Without a worker running, uploads still create jobs but stay in `pending`.

**Prerequisites:** Postgres reachable at `DATABASE_URL`, migrations applied, and **agent-normalizer** `make api` running when testing agent-backed imports. See `[tests/agents/AGENTIC_TESTING.md](tests/agents/AGENTIC_TESTING.md)` for the live smoke script (`make test-agent-service`).

## Testing


| Command                       | What it runs                                                                                                                                                                                                                                                                                                                     |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `**make test**`               | **pytest** on `tests/` with `**--ignore=tests/agents`** (that folder is agentic docs + logs only, not pytest). Uses `**DATABASE_URL_DEVTEST**` from the [Makefile](Makefile) unless you override it.                                                                                                                             |
| `**make test-agent-service**` | Live **Agent Gateway** / Google ADK smoke (**not** pytest): `[scripts/test_agent_service/test_agent_service.sh](scripts/test_agent_service/test_agent_service.sh)`. Exercises `**POST /agents/process-file`** (PDF upload + streamed JSON extraction). See `[tests/agents/AGENTIC_TESTING.md](tests/agents/AGENTIC_TESTING.md)`. |


From `**backend/**`, `**make test**` runs:

```text
DATABASE_URL=<DATABASE_URL_DEVTEST> uv run pytest tests/ -v --ignore=tests/agents
```

Override the DB URL for one run:

```bash
make test DATABASE_URL_DEVTEST='postgresql+psycopg://user:pass@host:5432/dbname'
```

**Typical flow:** start Postgres, create DB, `**alembic upgrade head`**, copy `**.env.example**` → `**.env**`, then `**make test**`. Integration tests need data the API expects (e.g. `**accounts**` row for `**DEFAULT_ACCOUNT_ID**` when posting transactions).

```bash
make test
make test-agent-service   # requires agent-normalizer `make api` + API up; see AGENTIC_TESTING.md
```

