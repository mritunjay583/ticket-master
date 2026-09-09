# Ticket-Master

A Support Ticket Management System with asynchronous ticket processing.

Python 3.12 · FastAPI · PostgreSQL · SQLAlchemy 2.0 · Alembic · Redis + RQ · Docker Compose

> This project is built in reviewable phases. See `docs/IMPLEMENTATION_PLAN.md` for the plan and
> `docs/ARCHITECTURE.md` for design decisions and tradeoffs.

## Status

- **Phase 0 — Foundation & walking skeleton:** ✅ done
  (config, structured logging, response envelope, typed errors, DB layer, ports + DI container,
  app factory with lifespan, request-id middleware, `/health`, Docker Compose with api + postgres)
- Phase 1 — Data model & migrations: pending
- Phase 2 — Ticket core API: pending
- Phase 3 — Async processing: pending

## Run locally (Docker)

```bash
docker compose up --build
```

Then:

```bash
curl -i http://localhost:8000/health
```

Interactive API docs (Swagger): http://localhost:8000/docs

## Dependencies & reproducible builds (uv)

Dependencies are declared in `pyproject.toml` (abstract ranges) and pinned in `uv.lock`
(exact versions of all direct + transitive packages). Both files are committed. The Docker image
installs strictly from the lockfile (`uv sync --frozen`) so every build is byte-for-byte reproducible.

Bare-metal dev setup (creates a `.venv` on Python 3.12 matching the Docker image):

```bash
pip install uv
uv sync --python 3.12 --extra dev   # .venv with exact locked deps + dev tools (ruff/mypy/pytest)
uv run uvicorn app.main:app --reload
```

Point your IDE at `.venv/bin/python` (VS Code does this automatically via the committed
`.vscode/settings.json`). This makes local autocomplete, linting, and type-checking match the
container exactly. Run the same checks CI runs:

```bash
uv run ruff check app
uv run mypy app
uv run pytest
```

When you change dependencies in `pyproject.toml`, regenerate the lock and commit it:

```bash
uv lock                 # re-resolve pyproject.toml -> uv.lock
```

## Environment variables

See `.env.example`. Docker Compose injects these automatically; for a bare-metal run, copy
`.env.example` to `.env`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENVIRONMENT` | `local` | `local` / `dev` / `stage` / `prod` |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `DATABASE_URL` | see file | SQLAlchemy (psycopg v3) URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Queue broker (Phase 3+) |

## Project layout

See `docs/ARCHITECTURE.md` §8. Business logic (`app/services`) depends only on interfaces in
`app/core/ports`; concrete tech is wired in `app/core/container.py`.
