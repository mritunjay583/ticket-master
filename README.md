# Ticket-Master

A production-style **Support Ticket Management System** with asynchronous ticket processing.

**Stack:** Python 3.12 · FastAPI · PostgreSQL · SQLAlchemy 2.0 · Alembic · Redis + RQ · Docker Compose

---

## 1. Project overview

Ticket-Master lets customers open support tickets, lets agents move tickets through a controlled
status lifecycle, and processes each new ticket asynchronously in the background.

- **Customers** create tickets (name, email, subject, description, priority, category).
- **Agents** update ticket status through a validated state machine
  (`OPEN → IN_PROGRESS → RESOLVED → CLOSED`, with controlled reopen).
- **A background worker** processes each new ticket: generates a summary, detects spam, assigns a
  priority, and routes it to a department — storing the result and applying priority/department to
  the ticket.
- Every state change and processing outcome is recorded in an **append-only audit history**.

## 2. Architecture decisions

The design follows **Hexagonal Architecture (Ports & Adapters)**: business logic depends on
interfaces (ports), never on concrete technology, so the database or queue can be swapped by writing
a new adapter and changing one line in the composition root.

```
HTTP → Router (API) → Service (domain) → Port (interface) ← Adapter (SQLAlchemy / RQ) → Postgres / Redis
                          │ owns the transaction (Unit of Work)
                          └ raises typed domain errors → one exception handler → response envelope
```

Key decisions (full rationale in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)):

| Decision | Why |
|----------|-----|
| **FastAPI** | Typed request/response validation (Pydantic) + free OpenAPI docs; async-friendly. |
| **PostgreSQL + SQLAlchemy 2.0 + Alembic** | Relational integrity, native enums, indexes; typed ORM; versioned migrations. |
| **Redis + RQ** | Lightweight task queue for one job type; one-command-local. Behind a `TaskQueue` port → swappable for SQS/Celery. |
| **Ports & Adapters + DI container** | Business logic isolated from tech; testable with fakes; swappable backends. |
| **Standard response envelope + typed errors** | Predictable client contract; centralized error handling. |
| **State machine for status** | Invalid transitions rejected with `409`; single source of truth. |
| **Separate `processing_results` table** | Async output has a different lifecycle than the ticket; clean 1:1 audit of what the worker decided. |
| **Dedicated `migrate` service + sweeper** | Migrations run once before the app; a sweeper guarantees at-least-once processing. |

**Layers** (`app/`): `api/` (HTTP) → `services/` (domain) → `core/ports/` (interfaces) →
`repositories/` + `adapters/` (concrete tech) → `models/` (ORM). Wiring lives only in
`core/container.py`.

## 3. Setup & how to run locally

**Prerequisites:** Docker + Docker Compose. Nothing else.

```bash
docker compose up --build
```

That single command orchestrates everything:
1. **db** (PostgreSQL) starts and becomes healthy.
2. **redis** starts (with AOF persistence) and becomes healthy.
3. **migrate** (one-shot) applies Alembic migrations and seeds sample data (local/dev only), then exits.
4. **api** starts once migrations succeed → available at `http://localhost:8000`.
5. **worker** starts consuming background jobs and runs the reliability sweeper.

Verify:
```bash
curl -i http://localhost:8000/health
```

## 4. API documentation access

Interactive docs are served by the API:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **OpenAPI JSON:** http://localhost:8000/openapi.json

### Endpoints

| Method | Path | Purpose | Success | Errors |
|--------|------|---------|---------|--------|
| `POST` | `/api/v1/tickets` | Create a ticket | `201` | `422` |
| `GET` | `/api/v1/tickets/{id}` | Retrieve by ID | `200` | `404` |
| `GET` | `/api/v1/tickets` | List — `?status=&priority=&category=&page=&page_size=` | `200` | `422` |
| `PATCH` | `/api/v1/tickets/{id}/status` | Update status (state machine) | `200` | `404`, `409` |
| `GET` | `/api/v1/tickets/{id}/events` | Audit history | `200` | `404` |
| `GET` | `/health` | Liveness/readiness | `200` | `503` |

All responses use the envelope:
```json
{ "success": true, "message": "Ticket created", "data": { "...": "..." },
  "error": null, "meta": { "page": 1, "page_size": 20, "total": 137 } }
```

Example — create a ticket:
```bash
curl -X POST http://localhost:8000/api/v1/tickets \
  -H 'Content-Type: application/json' \
  -d '{"customer_name":"Jane Doe","customer_email":"jane@example.com",
       "subject":"Cannot log in","description":"Error on login since this morning.",
       "priority":"HIGH","category":"TECHNICAL"}'
```

## 5. Environment variables

Copy `.env.example` to `.env` for bare-metal runs; Docker Compose injects sensible local defaults.
All values in `.env.example` are **local-dev defaults** — production values come from the platform's
secret manager, never from committed files.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENVIRONMENT` | `local` | `local` / `dev` / `stage` / `prod` (gates seeding) |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `DATABASE_URL` | see file | SQLAlchemy (psycopg v3) connection URL |
| `REDIS_URL` | `redis://redis:6379/0` | Queue broker |
| `QUEUE_NAME` | `tickets` | RQ queue name |
| `JOB_MAX_RETRIES` | `3` | Retries (with backoff) for failed jobs |
| `SWEEPER_INTERVAL_SECONDS` | `60` | How often the sweeper scans for stuck tickets |
| `SWEEPER_STALE_AFTER_SECONDS` | `120` | A `PENDING` ticket older than this is re-enqueued |

## 6. Development

Local environment mirrors the Docker image (Python 3.12 + exact locked deps via `uv`):
```bash
pip install uv
uv sync --python 3.12 --extra dev     # .venv with locked deps + dev tools
uv run ruff check app tests           # lint
uv run mypy app                       # type-check
uv run pytest                         # tests (API/integration tests need a running Postgres)
```

Migrations (generated locally, applied automatically on `docker compose up`):
```bash
uv run alembic revision --autogenerate -m "describe change"   # generate, then review + commit
uv run alembic upgrade head                                   # apply
```

## 7. Async processing & reliability

On ticket creation the API enqueues a job **after the DB commit**; the worker runs the pipeline and
persists the result. The design guarantees **at-least-once** processing:

- **Postgres is the source of truth** — a ticket carries `processing_status = PENDING` until done.
- **Sweeper** re-enqueues tickets stuck in `PENDING` (recovers enqueue failures / lost jobs).
- **RQ retries + failed registry** handle transient errors / dead-letter.
- **Redis AOF** persists the queue across restarts.
- **Idempotent jobs** make re-processing safe (no duplicate results).

Verified by flushing Redis mid-flight and confirming full recovery. Details in
[`docs/learning/LEARNING_PHASE4_RELIABILITY.md`](docs/learning/LEARNING_PHASE4_RELIABILITY.md).

## 8. Project structure

```
app/
├── main.py               # app factory + lifespan
├── api/                  # HTTP layer (routers, middleware) — /api/v1/tickets, /health
├── schemas/              # Pydantic DTOs + shared enums
├── services/             # domain logic + state machine (depends only on ports)
├── core/
│   ├── ports/            # abstract interfaces (TicketRepository, TaskQueue, ...)
│   ├── container.py      # composition root (the one place tech is wired)
│   ├── config.py errors.py response.py db.py logging.py
├── repositories/         # SQLAlchemy adapters (implement the repo ports)
├── adapters/             # queue (RQ) + processing (summary) adapters
├── models/               # SQLAlchemy ORM models
└── worker/               # RQ worker entrypoint + pipeline + sweeper
alembic/                  # migrations           scripts/  # migrate.sh, seed.py
tests/                    # unit + API integration tests
docs/                     # ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, learning/ (deep-dives)
```

## 9. Tradeoffs & assumptions

| Area | Choice | Tradeoff / assumption |
|------|--------|-----------------------|
| Auth | None (out of scope) | **Endpoints are unauthenticated** — a real deployment needs auth middleware. Flagged intentionally. |
| Queue | Redis + RQ | Simple & local-friendly; less feature-rich than Celery, less durable than SQS. Abstracted behind a port for easy swap. |
| Summary / spam / routing | Deterministic heuristics | No ML — the brief permits simulation. Each step is isolated behind a clean boundary for later replacement (e.g. an LLM summary provider). |
| DB driver | Sync SQLAlchemy | Simpler tooling; not end-to-end async. Fine for this CRUD workload. |
| Reopen policy | `RESOLVED/CLOSED → OPEN` allowed | Assumption encoded in the state machine; easily changed. |
| Pagination | Offset/limit + `total` | Simple and adequate; keyset pagination noted for very large tables. |
| Migrations in prod | One-shot service here | Production would run them as a pre-deploy step (init-container / Job), not per-replica app startup. |
| Outbox | `processing_status` + sweeper | A pragmatic transactional outbox; a dedicated outbox table + relay is the next step at higher scale. |

## 10. Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full design: ADRs, HLD, data model, API, tradeoffs.
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — the phased build plan and review gates.
- [`docs/learning/`](docs/learning) — optional deep-dive notes (config/12-factor, ports & adapters,
  SQLAlchemy, request lifecycle, migrations in production, async, reliability). These are
  learning/reference material, not required to run or review the service.
