# Ticket-Master — Architecture & Design

> Support Ticket Management System with asynchronous ticket processing.
> Python 3.12 · FastAPI · PostgreSQL · SQLAlchemy 2.0 · Alembic · Redis + RQ · Docker Compose

This document captures the **project overview**, **architecture decisions**, **high-level
design**, and the **tradeoffs** behind each choice. The design draws on patterns proven in
large-scale, event-driven ticketing platforms — consumer/worker services, service/repository
separation, a standardized response envelope, structured typed errors, config-by-environment,
and observability — while right-sizing them for a single-service assignment.

> **Proven patterns applied.** The following are well-established practices in production
> ticketing/event-driven systems, adopted here at an appropriate scale:
> - **Async summary generation as a first-class concern.** Mature ticketing systems run a
>   dedicated worker/consumer that reads ticket events off a queue and asynchronously generates a
>   **summary** (often sentiment too), then stores the result. This shapes our worker pipeline (§3.4).
> - **Standardized response envelope** — a consistent `{ status_code, request_id, message,
>   success, data, error, meta }` shape built with a fluent builder and emitted by a single
>   responder that sets `Content-Type`, `Cache-Control: no-store`, and echoes `x-request-id`.
>   Applied in §5.2 / §6.
> - **Structured typed errors** — a domain error type carrying `code` + `description` +
>   `additional_info`, wrapped with an HTTP `status_code`. Applied by our exception hierarchy in §6.
> - **Clean server bootstrap** — `new_router → register_routes → apply_middleware → apply_cors`,
>   warm required caches on startup (fail fast if unavailable), run background refresh tasks, and
>   shut down gracefully on SIGINT/SIGTERM. Applied by the FastAPI app factory + lifespan in §8.
> - **Consumer/worker resilience** — manual/at-least-once acknowledgement, periodic reconnect, and
>   per-message tracing spans. Applied (right-sized) by our RQ worker in §3.4.

---

## 1. Project Overview

### 1.1 Problem statement

Build a backend service that lets:

- **Customers** create support tickets.
- **Agents** update ticket status through a controlled lifecycle.
- **Background workers** process each new ticket asynchronously (summary, priority scoring,
  spam detection, department routing) and persist the result.

### 1.2 Goals

| # | Goal | How it is met |
|---|------|---------------|
| 1 | Clean, maintainable Python service | Layered architecture (API → Service → Repository → DB), strict typing, `ruff` + `mypy` |
| 2 | Well-structured REST API | Resource-oriented routes, correct status codes, consistent envelope, OpenAPI/Swagger |
| 3 | Effective relational modeling | Normalized schema, FKs, native PG enums, indexes, audit timestamps, migrations |
| 4 | Backend best practices | Pydantic v2 schemas (DTOs), enums, service abstraction, centralized error handling, structured logging |
| 5 | Async processing | Ticket-created event → Redis queue → worker pipeline → results stored in DB |
| 6 | Production-style dev setup | One-command `docker compose up`, seed script, health checks, env-based config |

### 1.3 Non-goals (explicit scope boundaries)

- No real authentication provider (a lightweight API-key / header check is stubbed; see §7).
- No real ML for summary/spam — these are **deterministic simulations** as the brief allows.
- No multi-tenant isolation, no horizontal DB sharding. These are noted as future work.

### 1.4 Design patterns & swappability (why components are easy to replace)

The overriding structural goal: **business logic must not depend on any specific technology.**
Changing the database, the queue, or any external integration should mean *writing a new adapter
and flipping one line of wiring* — never editing services, routers, or domain rules. This is
achieved with **Ports & Adapters (Hexagonal Architecture)** driven by the **Dependency Inversion
Principle**.

**The rule of dependency:** dependencies point *inward*. Concrete tech (SQLAlchemy, Redis, RQ)
depends on abstractions; the domain never depends on concrete tech.

```
        Routers ─▶ Services ─▶  PORTS (abstract interfaces)  ◀─ implemented by ─┐
        (API)      (domain)     • TicketRepository (Protocol/ABC)               │
                                • TaskQueue        (Protocol)          ADAPTERS │
                                • SummaryProvider / Clock / …          (swappable)
                                                                                │
             ┌──────────────────────────────────────────────────────────────┘
             ▼                         ▼                        ▼
   SqlAlchemyTicketRepository   RQTaskQueue / SqsTaskQueue   DeterministicSummaryProvider
   (Postgres today,             (Redis today,               (rule-based today,
    Mongo/other later)           SQS/Kafka later)            LLM API later)
```

**Patterns used and what each buys us:**

| Pattern | Where | What it enables |
|---|---|---|
| **Repository** | `repositories/` behind `TicketRepository` port | Swap Postgres → any store by writing a new repo class. Services never see SQL/ORM. |
| **Ports & Adapters / Dependency Inversion** | `core/ports/` (interfaces) + `adapters` | The whole app is written against interfaces; tech is plugged in at the edge. |
| **Strategy** | `TaskQueue`, `SummaryProvider`, spam/routing steps | Interchangeable algorithms/backends chosen by config (RQ vs SQS; rule-based vs LLM summary). |
| **Dependency Injection** | FastAPI `Depends` + a small `container`/providers module | One place wires concrete adapters to ports. Tests inject fakes/mocks trivially. |
| **Factory** | `create_task_queue(settings)`, `create_engine(settings)` | Config decides which adapter is built; call sites are unaware. |
| **Unit of Work** | session-per-request transaction boundary in the service layer | Atomic multi-repo writes (ticket + event) without leaking transaction handling into repos. |
| **Builder** | `Envelope` response builder | Consistent, fluent response construction. |
| **App Factory + Lifespan** | `main.py` | Bootstrap/teardown isolated and testable. |

**Concrete swap examples (the acceptance test for this design):**

- **Change the database** (Postgres → e.g. MySQL/Mongo): implement a new class satisfying the
  `TicketRepository` port; register it in the DI wiring. Services, routers, schemas, state machine,
  and tests are untouched. (ORM-level engine swaps like Postgres→MySQL are even smaller — often just
  the connection URL.)
- **Change the queue** (RQ → SQS or Kafka): implement `SqsTaskQueue`/`KafkaTaskQueue` against the
  `TaskQueue` port; flip `QUEUE_BACKEND` in config. Enqueue call sites and the pipeline logic don't
  change. (This is exactly the upgrade path in ADR-3 / §5.3.)
- **Change summary generation** (rule-based → LLM): implement a new `SummaryProvider`; inject it.
  The worker pipeline is unaware — summary generation is a pluggable step, not a hardcoded call.

**Guardrails that keep this true over time:**

- Ports live in `core/ports/` and import **nothing** from adapter packages.
- Services accept ports via constructor/DI — they must not import `sqlalchemy`, `redis`, or `rq`.
- All wiring (concrete → port) happens in exactly one place (`core/container.py` / `main.py`).
- Enforced in review by the Definition of Done ("services must not import concrete tech").

---

## 2. Architecture Decisions

Each decision is written as a short ADR (context → decision → why → tradeoff / rejected option).

### ADR-1 — Framework: FastAPI (over Flask)

- **Decision:** FastAPI + Uvicorn.
- **Why:** First-class Pydantic v2 integration gives request/response validation and OpenAPI docs
  for free; native `async def` fits an I/O-bound API that also enqueues jobs; type hints are
  idiomatic and enforced.
- **Tradeoff:** Slightly steeper learning curve than Flask and a younger ecosystem. Accepted
  because the assignment explicitly rewards typing, schemas, and Swagger — all FastAPI strengths.
- **Rejected:** Flask (more boilerplate for validation and OpenAPI; sync-first).

### ADR-2 — Database: PostgreSQL + SQLAlchemy 2.0 (ORM) + Alembic

- **Decision:** PostgreSQL with the SQLAlchemy 2.0 typed ORM and Alembic migrations.
- **Why:** Relational integrity (FKs, constraints), native `ENUM` types, partial/composite indexes,
  and transactional guarantees the domain needs. SQLAlchemy 2.0 gives typed models and a mature
  migration story via Alembic; the Repository layer keeps ORM details out of business logic.
- **Tradeoff:** ORM adds a small abstraction cost vs raw SQL and can hide expensive queries.
  Mitigated by keeping data access in repositories where SQL can be tuned or dropped to Core.
- **Rejected:** Raw `asyncpg` + hand-rolled SQL (faster, but more boilerplate and error-prone for
  a CRUD-heavy service); an ODM/NoSQL store (loses relational modeling the brief asks for).

### ADR-3 — Async processing: Redis + RQ (over Celery / SQS)

- **Decision:** Redis as broker with **RQ** for the worker.
- **Why:** Minimal moving parts, trivial to run in Compose, readable job semantics, and enough for
  the required pipeline. The queue boundary is abstracted behind a `TaskQueue` interface so the
  backend can be swapped for **AWS SQS** or **Celery** without touching call sites.
- **Tradeoff:** RQ is Redis-only and less feature-rich than Celery (no complex routing/chords) and
  lacks SQS's managed durability. Acceptable for the assignment; the abstraction preserves the
  upgrade path (documented in §5.3).
- **Rejected:** Celery (heavier config, more than needed); FastAPI `BackgroundTasks` (runs in the
  API process — no isolation, lost on restart, not a real queue); AWS SQS (needs cloud creds,
  harder for a one-command local run — kept as the documented production target).

### ADR-4 — Sync DB driver in a mostly-async app (pragmatic choice)

- **Decision:** Use SQLAlchemy's synchronous engine (`psycopg`) with a thread-pool, exposed through
  repositories; keep the transport layer async.
- **Why:** Alembic, RQ workers, and the ORM are simplest and most battle-tested in sync mode. The
  CRUD workload is light; correctness and clarity beat micro-optimizing the driver.
- **Tradeoff:** Loses true end-to-end async DB I/O. Documented as a deliberate simplification; the
  repository interface would allow moving to `asyncpg`/async sessions later.
- **Rejected:** Full async SQLAlchemy everywhere (more complexity, worse tooling story for a
  timeboxed assignment).

### ADR-5 — Status lifecycle as an explicit state machine

- **Decision:** Encode allowed transitions (`OPEN → IN_PROGRESS → RESOLVED → CLOSED`, with
  controlled reopen) in one place and reject invalid transitions with `409 Conflict`.
- **Why:** The brief explicitly asks for "validation for invalid state transitions." Centralizing
  the transition table makes the rule testable and prevents illegal states.
- **Tradeoff:** A tiny amount of extra structure vs a free-form status field. Worth it for
  correctness and auditability.

### ADR-6 — Standardized response envelope + structured typed errors

- **Decision:** Every response is wrapped in `{ success, message, data, error, meta }`; domain
  errors are raised as a typed hierarchy carrying `code` + `description` + optional
  `additional_info`, and a single exception-handler layer maps them to HTTP codes + envelope.
- **Why:** Follows the proven envelope-builder + typed-error pattern from production ticketing
  systems. Consumers get a predictable shape and machine-readable error `code`s; error handling is
  centralized, not scattered across handlers.
- **Tradeoff:** Slightly less "idiomatic FastAPI" (which returns bare models and raw
  `HTTPException`). Chosen for consistency with the production contract and better client ergonomics.

### ADR-7 — Immutable ticket event/history table (audit trail)

- **Decision:** Every state change and processing result writes an append-only row to
  `ticket_events`.
- **Why:** Gives a full audit timeline (who/what/when), satisfies the "ticket events/history"
  requirement, and decouples the current-state row from its change log.
- **Tradeoff:** Extra writes and storage growth. Acceptable and standard for support systems;
  retention/TTL is noted as future work.

---

## 3. High-Level Design

### 3.1 Component diagram

```
                              ┌──────────────────────────────────────────┐
                              │                Clients                     │
                              │        (Swagger UI / curl / Postman)       │
                              └───────────────────┬────────────────────────┘
                                                  │ HTTP (JSON)
                                                  ▼
        ┌───────────────────────────────────────────────────────────────────────┐
        │                       API Service (FastAPI / Uvicorn)                    │
        │                                                                          │
        │   Middleware:  Request-ID · access log · exception → envelope            │
        │                                                                          │
        │   ┌──────────────┐   ┌──────────────┐   ┌───────────────────────────┐   │
        │   │  Routers     │──▶│   Services    │──▶│      Repositories          │   │
        │   │ (API layer)  │   │ (domain logic │   │ (data access, SQLAlchemy)  │   │
        │   │  DTO in/out  │   │  state machine│   │                            │   │
        │   └──────────────┘   │  enqueue job) │   └────────────┬──────────────┘   │
        │                      └───────┬───────┘                │                  │
        └──────────────────────────────┼────────────────────────┼──────────────────┘
                                        │ enqueue                │ SQL
                                        ▼                        ▼
                             ┌────────────────────┐   ┌────────────────────────┐
                             │   Redis (broker)    │   │     PostgreSQL          │
                             │   RQ "tickets" queue│   │  tickets / ticket_events│
                             └─────────┬──────────┘   │  agents  / processing…  │
                                       │ dequeue      └───────────▲────────────┘
                                       ▼                          │ write results
                             ┌────────────────────────────────────┴─────────────┐
                             │            Worker Service (RQ worker)              │
                             │  Pipeline: summarize → prioritize → spam → route   │
                             │  writes ProcessingResult + ticket_events, updates  │
                             │  ticket status/priority/department                 │
                             └────────────────────────────────────────────────────┘
```

### 3.2 Layered responsibilities (separation of concerns)

| Layer | Package | Responsibility | Must NOT do |
|-------|---------|----------------|-------------|
| **API / Routers** | `app/api/v1/` | Parse & validate DTOs, call services, shape envelope, set status codes | Business rules, direct DB access |
| **Schemas (DTOs)** | `app/schemas/` | Pydantic request/response models, enums, validation | Persistence, side effects |
| **Services** | `app/services/` | Domain logic, state-machine enforcement, transaction orchestration, enqueue jobs | HTTP concerns, raw SQL |
| **Repositories** | `app/repositories/` | All DB reads/writes via SQLAlchemy, pagination/filter queries | Business decisions |
| **Models** | `app/models/` | SQLAlchemy ORM entities, table constraints, indexes | Request validation |
| **Core** | `app/core/` | Config, logging, error types, response envelope, DB session, queue client | Domain rules |
| **Worker** | `app/worker/` | Job entrypoints + processing pipeline steps | HTTP handling |

This is the same **Router → Service → Repository → DB** flow used by well-layered production
services (controllers → domain services → data-access interface → store), expressed in Python idioms.

### 3.3 Request flow — Create Ticket (happy path)

```
POST /api/v1/tickets
  → router validates CreateTicketRequest (Pydantic: email, enums, lengths)
  → TicketService.create_ticket()
      → TicketRepository.create()            # INSERT ticket (status=OPEN)
      → TicketEventRepository.add(CREATED)   # audit row
      → commit transaction
      → task_queue.enqueue(process_ticket, ticket_id)   # after commit
  → 201 Created  { success, data: TicketResponse }
```

The enqueue happens **after** the DB commit so a worker never sees a ticket that does not yet
exist (avoids a read-before-write race).

### 3.4 Async pipeline — `process_ticket(ticket_id)`

> This follows the proven "summary worker" pattern: a separate process consumes ticket events,
> generates a summary (production systems often derive sentiment too), and stores the result back —
> decoupled from the request path. We keep the same shape (event in → enrich → persist result) but
> use RQ instead of a streaming log to stay one-command-local, and add prioritize/spam/route steps
> the brief lists.

Runs in the worker, each step idempotent and persisted. The **full computed output is written to
`processing_results`** (this is "the processing result stored in the database" the brief asks for).
Two of those computed values are *also applied to the live ticket*, because the brief frames them as
actions on the ticket ("assign ticket priority", "route to the correct department"):

| Step | Computes | Written to `processing_results` | Also applied to `ticket` |
|------|----------|--------------------------------|--------------------------|
| 1. Summarize | short summary of subject+description | `summary` | — (artifact, not a ticket attribute) |
| 2. Prioritize | heuristic priority | `suggested_priority` | ✅ `ticket.priority` |
| 3. Spam detect | spam verdict | `is_spam` | — (verdict; spam ⇒ routed to triage) |
| 4. Route | category → department | `routed_department` | ✅ `ticket.department` |
| 5. Record | — | — | append `ticket_events` (`PROCESSED`); set `processing_status = DONE` |

**The suggested-vs-applied distinction:** `processing_results.suggested_priority` /
`routed_department` are the immutable record of *what the worker decided*; `ticket.priority` /
`ticket.department` are the *live, current* values an agent may later override. Keeping both lets us
audit the automated decision and measure how often humans override it. `summary` and `is_spam` are
processing artifacts, so they live **only** in `processing_results` (never bloat the ticket).

Failure handling: exceptions mark `processing_status = FAILED` and record the error; RQ retry with
backoff is configured, and a final failure is left inspectable (dead-letter behavior documented).

---

## 4. Data Model

Normalized (3NF) relational schema. Enums are **native PostgreSQL enum types**. All tables carry
`created_at` / `updated_at` audit timestamps.

```
agents                         tickets                              ticket_events
──────────                     ─────────                            ───────────────
id (PK)                        id (PK, UUID)                        id (PK)
name                           customer_name                        ticket_id (FK→tickets)
email (UNIQUE)                 customer_email                       event_type (enum)
department (enum)              subject                              from_status (enum, null)
is_active                      description                          to_status   (enum, null)
created_at / updated_at        status      (enum)  ── idx           actor        (text)
                               priority    (enum)  ── idx           note (jsonb)
                               category    (enum)  ── idx           created_at
                               department  (enum, null)
                               assigned_agent_id (FK→agents, null)  processing_results
                               processing_status (enum) ── idx      ──────────────────
                               created_at / updated_at ── idx       id (PK)
                                                                    ticket_id (FK→tickets, UNIQUE)
                                                                    summary (text)
                                                                    is_spam (bool)
                                                                    suggested_priority (enum)
                                                                    routed_department (enum)
                                                                    created_at / updated_at
```

**Enums:** `TicketStatus`, `TicketPriority`, `TicketCategory`, `Department`, `ProcessingStatus`,
`EventType` — defined once in `app/schemas/enums.py` and reused by both Pydantic and SQLAlchemy.

**Indexes (why):**
- `tickets(status)`, `tickets(priority)`, `tickets(category)` — the required list filters.
- `tickets(created_at)` — default ordering + keyset pagination.
- Composite `tickets(status, priority)` — common combined filter.
- `ticket_events(ticket_id, created_at)` — fast per-ticket timeline reads.

**Constraints:** FKs with `ON DELETE` policy, `NOT NULL` on required columns, `UNIQUE(agents.email)`
and `UNIQUE(processing_results.ticket_id)` (one result row per ticket).

**Migrations & seed:** Alembic migration creates enums, tables, indexes; a `seed.py` script inserts
sample agents and a handful of tickets across statuses/priorities for instant manual testing.

---

## 5. API Design

### 5.1 Endpoints

| Method | Path | Purpose | Success | Errors |
|--------|------|---------|---------|--------|
| `POST` | `/api/v1/tickets` | Create ticket (customer) | `201` | `422` validation |
| `GET`  | `/api/v1/tickets/{id}` | Retrieve by ID | `200` | `404` |
| `GET`  | `/api/v1/tickets` | List — pagination + filter by status/priority/category | `200` | `422` |
| `PATCH`| `/api/v1/tickets/{id}/status` | Agent updates status (state machine) | `200` | `404`, `409` invalid transition |
| `GET`  | `/api/v1/tickets/{id}/events` | Audit timeline | `200` | `404` |
| `GET`  | `/health` | Liveness/readiness (DB + Redis) | `200` | `503` |

### 5.2 Response envelope

```json
// success
{ "success": true, "message": "Ticket created", "data": { "...": "..." }, "meta": null }

// list (meta carries pagination)
{ "success": true, "data": [ ... ], "meta": { "page": 1, "page_size": 20, "total": 137 } }

// error
{ "success": false, "message": "Invalid status transition",
  "error": { "code": "INVALID_TRANSITION", "detail": "CLOSED → IN_PROGRESS not allowed" } }
```

Status codes follow REST conventions: `200/201` success, `400/422` validation, `404` not found,
`409` conflict (invalid transition), `503` dependency down, `500` unexpected. Every response echoes
an `X-Request-ID` (generated if absent) for traceability — same pattern as the production platform.

### 5.3 Queue abstraction (upgrade path)

```python
class TaskQueue(Protocol):
    def enqueue(self, func: Callable, *args, **kwargs) -> str: ...

# RQ implementation now; SqsTaskQueue / CeleryTaskQueue later — call sites unchanged.
```

If the queue were **not** implemented, async processing would instead be described as: publish a
`ticket.created` event to SQS/Redis on commit; a separate worker consumes, runs the pipeline
idempotently (keyed by ticket_id), and writes results back — the standard consumer/worker model for
event-driven ticketing systems.

---

## 6. Cross-Cutting Concerns

- **Configuration:** `pydantic-settings` reads a typed `Settings` object from environment variables
  (`.env` for local). No secrets in code. Env-per-stage is the standard 12-factor config approach.
- **Logging:** Structured JSON logs with request-id correlation; log level via `LOG_LEVEL`.
- **Error handling:** A typed exception hierarchy —
  a base `AppError(code, description, status_code, additional_info)` with concrete subclasses
  (`NotFoundError` → 404, `InvalidTransitionError` → 409, `ValidationError` → 422,
  `ConflictError` → 409). Raised in the service layer, caught by one exception handler that
  renders the envelope with a machine-readable `error.code`.
- **Validation:** Pydantic v2 at the edge (types, enums, email, length bounds) + business validation
  (state machine) in the service layer.
- **Testing:** `pytest` unit tests for the state machine and services (mocked repositories), plus API
  tests against a test DB. Repositories behind interfaces make mocking clean — a data-access
  interface with a mock/fake implementation for tests.
- **App bootstrap & lifecycle:** A FastAPI **app factory** + `lifespan` handler: build app →
  register routers → attach middleware/CORS → on startup verify dependencies (DB + Redis) and fail
  fast if unavailable → on shutdown dispose the engine and close the Redis pool gracefully. Uvicorn
  handles SIGINT/SIGTERM.
- **Observability hook:** OpenTelemetry is left as a documented extension point (a span per request
  and per consumed message); not wired by default here to keep the local run light. Request-ID
  correlation is wired.

---

## 7. Tradeoffs & Assumptions

| Area | Choice | Tradeoff / Assumption |
|------|--------|-----------------------|
| Auth | Stubbed header/API-key check | Real IdP out of scope; interface allows dropping in JWT/OAuth. **Endpoints are otherwise unauthenticated — flagged, not production-safe as-is.** |
| Queue | Redis + RQ | Simple & local-friendly; less durable/feature-rich than SQS/Celery. Abstracted for swap. |
| DB driver | Sync SQLAlchemy | Simpler tooling; not end-to-end async. Fine for CRUD workload. |
| Summary/spam/routing | Deterministic simulation | No ML; brief permits simulation. Logic isolated in pipeline steps for later replacement. |
| Reopen policy | `RESOLVED/CLOSED → OPEN` allowed with reason | Assumption; encoded in the transition table and easily changed. |
| Pagination | Offset/limit with `meta.total` | Simple and adequate; keyset pagination noted for large tables. |
| Multi-tenancy / sharding | Not implemented | Single-tenant assumption for the assignment. |

---

## 8. Proposed Project Structure

The layout makes the **ports vs adapters** split physical: `core/ports/` holds the abstract
interfaces (imported by services), and the concrete tech lives in `repositories/` and
`adapters/` (imported only by the wiring in `core/container.py`).

```
ticket-master/
├── app/
│   ├── main.py                 # app factory + lifespan; builds container, mounts routers/middleware
│   ├── api/v1/
│   │   ├── tickets.py          # ticket routes (create/get/list/update-status/events)
│   │   └── health.py
│   ├── schemas/                # DTOs — request/response models (Pydantic)
│   │   ├── enums.py            # shared enums (status, priority, category, department, ...)
│   │   ├── ticket.py           # CreateTicketRequest, UpdateStatusRequest, TicketResponse, ...
│   │   └── common.py           # Envelope, Pagination meta
│   ├── services/               # DOMAIN — depends ONLY on core/ports, never on concrete tech
│   │   ├── ticket_service.py   # domain logic + enqueue (takes ports via constructor)
│   │   └── state_machine.py    # allowed status transitions table
│   ├── core/
│   │   ├── ports/              # ── PORTS (abstract interfaces / Protocols) ──
│   │   │   ├── ticket_repository.py   # TicketRepository interface
│   │   │   ├── event_repository.py    # TicketEventRepository interface
│   │   │   ├── task_queue.py          # TaskQueue interface
│   │   │   └── summary_provider.py    # SummaryProvider / spam / routing strategy interfaces
│   │   ├── container.py        # ── the ONE wiring place: concrete adapters → ports (DI) ──
│   │   ├── config.py           # pydantic-settings (chooses which adapters to build)
│   │   ├── logging.py
│   │   ├── errors.py           # AppError hierarchy + FastAPI exception handlers
│   │   ├── response.py         # Envelope builder
│   │   └── db.py               # engine/session factory + Unit-of-Work helper
│   ├── repositories/           # ── ADAPTERS: persistence (SQLAlchemy today) ──
│   │   ├── sqlalchemy_ticket_repository.py
│   │   └── sqlalchemy_event_repository.py
│   ├── adapters/               # ── ADAPTERS: other tech behind ports ──
│   │   ├── queue/
│   │   │   ├── rq_task_queue.py       # RQTaskQueue (today)
│   │   │   └── sqs_task_queue.py      # SqsTaskQueue (future — same port)
│   │   └── processing/
│   │       └── deterministic_summary.py  # rule-based SummaryProvider (LLM swap later)
│   ├── models/                 # SQLAlchemy ORM entities (persistence detail)
│   │   ├── base.py             # declarative base + timestamp mixin
│   │   ├── ticket.py
│   │   ├── ticket_event.py
│   │   ├── processing_result.py
│   │   └── agent.py
│   └── worker/
│       ├── worker.py           # RQ worker entrypoint (builds same container)
│       └── pipeline/           # summarize / prioritize / spam / route steps (strategies)
├── alembic/                    # migrations
├── scripts/seed.py             # seed data
├── tests/                      # unit (fake adapters) + api (test DB)
├── docker-compose.yml          # api + worker + postgres + redis
├── Dockerfile
├── .env.example
├── pyproject.toml              # deps, ruff, mypy, pytest config
└── README.md
```

**Why this layout enforces swappability:**
- `services/` may import from `core/ports/` and `schemas/` — **never** from `repositories/`,
  `adapters/`, `models/`, `sqlalchemy`, `redis`, or `rq`.
- `core/ports/` imports nothing from adapters (no cycles; the domain stays pure).
- `core/container.py` is the **single** place that knows concrete classes; swapping a backend is a
  one-line change there plus a new adapter file.
- This is the "clear project structure / separation of concerns" the brief calls out, made
  physically enforceable rather than a convention.
```
