# Ticket-Master — Implementation Plan

> Companion to `ARCHITECTURE.md`. This is the build checklist and review contract.
> Read `ARCHITECTURE.md` first for the *what/why*; this doc is the *how/when/in-what-order*.

## Guiding approach

**Outside-in, walking-skeleton + vertical slices** (not pure top-down or bottom-up).

- **Phase 0** builds a *walking skeleton*: the thinnest end-to-end path (API → service → repo →
  real Postgres → envelope response) running in Docker. Proves the whole stack wires together on
  day one.
- **Every phase after** adds a **vertical slice** — a slice cuts through all layers for one
  capability and leaves the app fully runnable. Within a slice we build bottom-up
  (enum/model → repository → service → schema → route → test), but the *unit of progress is a
  working feature*, not a layer.
- **Each phase ends at a review gate.** Nothing proceeds until the gate passes. This keeps a large
  build small, reviewable, and always demoable.

## Locked stack

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| Web framework | FastAPI + Uvicorn |
| DB | PostgreSQL |
| ORM / migrations | SQLAlchemy 2.0 (typed) + Alembic |
| Async queue | Redis + RQ (behind a `TaskQueue` protocol) |
| Config | pydantic-settings |
| Tooling | ruff (lint/format), mypy (types), pytest (tests) |
| Packaging / run | Docker + Docker Compose (one-command up) |

> Any stack change (Flask instead of FastAPI, SQS instead of RQ, etc.) should be decided before
> Phase 0 — it changes the skeleton.

## Definition of Done (applies to every slice)

- [ ] Type hints on all public functions; `mypy` clean.
- [ ] `ruff` lint + format clean.
- [ ] Pydantic schema validates input; correct HTTP status codes; responses use the envelope.
- [ ] Domain errors raised as typed exceptions (no bare `HTTPException` in services).
- [ ] Unit test(s) for logic + at least one API test for the endpoint.
- [ ] No secrets in code; new config read via `Settings`.
- [ ] The app still runs end-to-end (`docker compose up`).
- [ ] **Swappability guardrail:** `services/` import only from `core/ports/` and `schemas/` — never
      from `repositories/`, `adapters/`, `models/`, or a concrete lib (`sqlalchemy`, `redis`, `rq`).
      All concrete→port wiring stays in `core/container.py`. (See `ARCHITECTURE.md` §1.4.)

---

## Phase 0 — Foundation & walking skeleton

**Goal:** the whole stack runs end-to-end with one real endpoint.

- [ ] Project scaffold: folder layout per `ARCHITECTURE.md` §8, `pyproject.toml`, tool config.
- [ ] `core/config.py` — typed `Settings` (env-based).
- [ ] `core/logging.py` — structured JSON logging + request-id correlation.
- [ ] `core/response.py` — `Envelope { success, message, data, error, meta }` builder.
- [ ] `core/errors.py` — `AppError(code, description, status_code, additional_info)` hierarchy
      (`NotFoundError`→404, `InvalidTransitionError`→409, `ValidationError`→422, `ConflictError`→409)
      + FastAPI exception handlers.
- [ ] `core/db.py` — engine + session dependency; `models/base.py` declarative base + timestamp mixin.
- [ ] `core/ports/` — define the abstract interfaces first (`TicketRepository`,
      `TicketEventRepository`, `TaskQueue`, `SummaryProvider`); `core/container.py` — the single
      DI wiring point (concrete adapters → ports). Establishes Ports & Adapters from line one.
- [ ] `main.py` — app factory + `lifespan` (startup: verify DB reachable; shutdown: dispose engine).
- [ ] Request-ID middleware (generate if absent, echo `x-request-id`).
- [ ] `GET /health` — returns envelope, checks DB connectivity.
- [ ] `Dockerfile` + `docker-compose.yml` with **api + postgres** services.

**✅ Review gate 0:** `docker compose up` → `GET /health` returns `{ success: true, ... }` and
reports DB reachable. Envelope + error handler verified with a deliberate bad route (404 envelope).

---

## Phase 1 — Data model & migrations

**Goal:** the relational schema exists, is migratable, and is seedable.

- [x] `schemas/enums.py` — `TicketStatus`, `TicketPriority`, `TicketCategory`, `Department`,
      `ProcessingStatus`, `EventType`.
- [x] Models: `agent.py`, `ticket.py`, `ticket_event.py`, `processing_result.py`
      (FKs, `NOT NULL`, uniques, native PG enums, audit timestamps, `processing_status` column).
- [x] Indexes: `tickets(status)`, `(priority)`, `(category)`, `(created_at)`, composite
      `(status, priority)`, `(processing_status)`, `ticket_events(ticket_id, created_at)`.
- [x] Alembic setup + initial migration (creates enum types, tables, indexes, constraints;
      enums managed explicitly for a clean upgrade/downgrade roundtrip).
- [x] `scripts/seed.py` — sample agents + tickets across statuses/priorities/categories (idempotent).
- [x] Tightened repository ports from `Any` placeholders to concrete types (`Ticket`, `TicketFilter`).

**✅ Review gate 1 — PASSED:** on a fresh DB, `alembic upgrade head` runs clean; `seed.py` populates
(4 agents, 4 tickets); schema matches `ARCHITECTURE.md` §4; upgrade→downgrade→upgrade roundtrip works.

---

## Phase 2 — Ticket core API (heart of the assignment)

**Goal:** all required ticket endpoints work with correct validation and status codes.
Built as four vertical slices.

- [ ] **Slice 2a — Create Ticket** `POST /api/v1/tickets`
      - `CreateTicketRequest` DTO (email, enums, length bounds) → `TicketRepository.create` →
        `TicketService.create_ticket` (writes `CREATED` event) → `201` + `TicketResponse`.
- [ ] **Slice 2b — Retrieve** `GET /api/v1/tickets/{id}` → `200` or `404` (envelope).
- [ ] **Slice 2c — List** `GET /api/v1/tickets`
      - pagination (`page`, `page_size`) + filters (status/priority/category) → `200` with
        `meta { page, page_size, total }`.
- [ ] **Slice 2d — Update Status** `PATCH /api/v1/tickets/{id}/status`
      - `services/state_machine.py` transition table → invalid transition → `409` →
        writes `STATUS_CHANGED` event.
- [ ] **Events read (supports history req.)** `GET /api/v1/tickets/{id}/events` → `200`.

**✅ Review gate 2:** every endpoint exercised in Swagger; valid + invalid inputs return correct
codes/envelope; invalid transition returns `409`; events recorded for create + status change.

---

## Phase 3 — Async processing

**Goal:** ticket creation triggers a background pipeline whose result is stored.

- [ ] `core/queue.py` — `TaskQueue` protocol + `RQTaskQueue` implementation.
- [ ] Enqueue **after commit** in `create_ticket`; ticket starts `processing_status = PENDING`.
- [ ] `worker/worker.py` entrypoint + `worker/pipeline/` steps:
      summarize → prioritize → spam-detect → route. Idempotent, keyed by `ticket_id`.
- [ ] Persist to `processing_results`; update ticket (priority/department); write `PROCESSED` event;
      set `processing_status = DONE` (or `FAILED` on error).
- [ ] Add **redis + worker** services to Compose.

**✅ Review gate 3:** create a ticket → worker consumes → `processing_results` row created,
`processing_status = DONE`, `PROCESSED` event logged. Failure path sets `FAILED` and records error.

---

## Phase 4 — Reliability hardening

**Goal:** no task lost on Redis/worker/API crash — at-least-once guarantee.

- [ ] Redis **AOF** persistence (`appendfsync everysec`) in Compose.
- [ ] RQ **retries with backoff** + **failed-job registry** (dead-letter equivalent).
- [ ] **Sweeper** job: re-enqueue tickets stuck in `PENDING` older than threshold.
- [ ] Confirm job **idempotency** (re-run safe via `processing_status` guard).
- [ ] Document the **Transactional Outbox** as the production-grade evolution.

**✅ Review gate 4:** kill Redis (or worker) mid-flight, restart → stuck `PENDING` ticket is
re-processed exactly once; no duplicate `processing_results`.

---

## Phase 5 — Polish & deliverables

**Goal:** clean, documented, one-command deliverable.

- [ ] OpenAPI/Swagger: tags, summaries, examples; served at `/docs`.
- [ ] `README.md`: overview, architecture summary, setup, env vars, run-locally,
      API docs access, tradeoffs & assumptions.
- [ ] `.env.example` with all env vars.
- [ ] Final test pass; `ruff` + `mypy` clean; remove dead code/temp files.
- [ ] Fresh-clone smoke test: single `docker compose up` → fully working.

**✅ Review gate 5:** fresh clone → one command → create/list/get/update-status + async result all
work; docs complete.

---

## Working agreement

1. I implement one phase at a time and stop at its review gate.
2. You review the diff; we adjust before moving on.
3. Commits are small and each is runnable (mirrors how the reviewer reads history).
4. This doc's checkboxes are the shared source of truth for progress.

## Out of scope (confirmed against the brief)

- Conversation / reply threads (customer↔agent messaging). The brief only requires **status
  transitions**; `ticket_events` provides the audit history instead.
- Real auth provider (a stubbed API-key/header check only; flagged as not production-safe).
- Real ML for summary/spam — deterministic simulation, per the brief.
