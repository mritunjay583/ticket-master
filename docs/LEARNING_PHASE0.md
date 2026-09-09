# Phase 0 — Deep Dive (Learning Notes)

> Purpose: understand **what** each file does, **why** it exists, **why it was built in this
> order**, and **why the folder structure is shaped this way**. This is your study companion — not
> the interview deliverable. Read it top to bottom once; after that it's a reference.

---

## 1. The mental model first

Before any file makes sense, hold this picture in your head:

```
        HTTP request
             │
             ▼
   ┌──────────────────┐   the "outside" — knows HTTP, JSON, status codes
   │   API layer       │   (routers + middleware)
   └────────┬─────────┘
            │ calls
            ▼
   ┌──────────────────┐   the "core" — business rules, no HTTP, no SQL
   │   Service layer   │   (depends only on PORTS)
   └────────┬─────────┘
            │ uses interfaces (ports)
            ▼
   ┌──────────────────┐   the "edge" — talks to real tech
   │  Adapters         │   (SQLAlchemy repos, Redis/RQ queue)
   └────────┬─────────┘
            │
            ▼
     Postgres / Redis
```

The single most important rule: **dependencies point inward.** The API knows about services;
services know about *interfaces* (ports); adapters implement those interfaces. The business logic
never imports `sqlalchemy` or `redis`. This is **Hexagonal Architecture / Ports & Adapters**, and
almost every decision in Phase 0 exists to make this rule *physically true*, not just a promise.

Why care? Because it's what makes "swap the database later" a one-file change instead of a rewrite,
and it's what makes the code testable without a real DB. This is the core "senior" signal.

---

## 2. The build order — and why this exact sequence

I built Phase 0 **from the inside out and bottom up**: the things with *no dependencies* first,
then things that depend on them, and the wiring (`main.py`) last. You can only import what already
exists, so the order is essentially a topological sort of the dependency graph.

Here is the actual order, grouped, with the reasoning:

### Group A — Project skeleton (no code logic yet)
| # | File | Why first |
|---|------|-----------|
| 1 | `pyproject.toml` | Declares the language version, dependencies, and tooling (ruff/mypy/pytest). Nothing can be imported or linted until the project is *defined*. It's the contract for "what this project is." |
| 2 | `app/__init__.py`, `app/core/__init__.py`, … | Make folders into Python *packages* so imports like `app.core.config` work. Structural, not logical. |

> **Why `pyproject.toml` over `requirements.txt`?** It's the modern standard (PEP 621): one file for
> dependencies *and* tool config (ruff, mypy, pytest all read from it). Fewer scattered config files.

### Group B — Foundational primitives (depend on nothing but stdlib/pydantic)
| # | File | Why here | Depends on |
|---|------|----------|------------|
| 3 | `core/config.py` | *Everything* eventually needs configuration (DB URL, log level). It reads env vars once into a typed object. Built first because DB, logging, and the app factory all consume it. | nothing |
| 4 | `core/logging.py` | Structured logging is needed by every other module that wants to log. No dependency on config's *values* (just takes a level string), so it's independent. | nothing |
| 5 | `core/response.py` | The response envelope is a pure data shape. Errors and endpoints both build envelopes, so it must exist before them. | pydantic only |

> Notice the pattern: **leaves of the dependency tree first.** `config`, `logging`, `response` don't
> import any other app module. That's why they're safe to build early.

### Group C — Error handling + persistence foundations
| # | File | Why here | Depends on |
|---|------|----------|------------|
| 6 | `core/errors.py` | Defines domain exceptions + the handlers that turn them into envelopes. Needs `response.py` (to build the envelope) and `logging.py`. | response, logging |
| 7 | `models/base.py` | The ORM base class + timestamp mixin. All future models inherit it, so it comes before any model and before the DB session logic that references models. | sqlalchemy |
| 8 | `core/db.py` | Engine, session factory, Unit-of-Work scope, health probe. Needs `config` (for the DB URL). Built after config but before anything that runs queries. | config |

### Group D — The abstraction boundary (ports) + wiring
| # | File | Why here | Depends on |
|---|------|----------|------------|
| 9 | `core/ports/*.py` | The *interfaces* (TicketRepository, TaskQueue, …). Deliberately built **before** any concrete implementation so the design forces "code to the interface." They depend on nothing. | nothing |
| 10 | `core/container.py` | The composition root — the one place that will wire concrete adapters to ports. In Phase 0 it only holds settings; it grows in later phases. | config |

> **Why define ports before implementations?** If you write the SQLAlchemy repo first, you're
> tempted to let its concrete methods leak into services. Writing the *interface* first flips your
> thinking: services are coded against the abstraction, and the DB is "just one implementation."

### Group E — HTTP layer + the wiring that ties it all together
| # | File | Why here | Depends on |
|---|------|----------|------------|
| 11 | `api/middleware.py` | Request-ID middleware. Needs `logging` (to set the context var). Independent of routes. | logging |
| 12 | `api/health.py` | The first real endpoint. Needs `response`, `config`, `db`. Proves the full path works. | response, config, db |
| 13 | `app/main.py` | **Last.** The app factory imports and wires *everything*: logging, container, DB engine, middleware, error handlers, routers. It can only be written once its parts exist. | almost everything |

### Group F — Runtime & delivery (not Python, but part of "runs end to end")
| # | File | Why last |
|---|------|----------|
| 14 | `Dockerfile` | Describes how to package the app. Meaningless until there's an app to package. |
| 15 | `docker-compose.yml` | Orchestrates api + postgres. Needs the Dockerfile and the DB URL convention from config. |
| 16 | `.env.example`, `README.md` | Document how to configure and run. Written once the shape is known. |

**The one-sentence version:** *build leaves before branches before the trunk* — config/logging/
response (leaves) → errors/db/ports (branches) → `main.py` (trunk) → Docker (delivery).

---

## 3. Why the folder structure looks like this

```
app/
├── main.py            # trunk: app factory + lifespan (wires everything)
├── api/               # OUTSIDE: HTTP concerns only (routers, middleware)
│   ├── health.py
│   └── middleware.py
├── core/              # INSIDE: framework-agnostic building blocks
│   ├── config.py      #   configuration
│   ├── logging.py     #   observability
│   ├── response.py    #   the response envelope
│   ├── errors.py      #   typed errors + handlers
│   ├── db.py          #   engine/session/UoW
│   ├── container.py   #   composition root (DI wiring)
│   └── ports/         #   ABSTRACT interfaces (the boundary)
├── models/            # persistence detail: ORM entities
├── services/          # (Phase 2) domain logic — depends only on ports
├── repositories/      # (Phase 2) SQLAlchemy adapters implementing repo ports
├── adapters/          # (Phase 3) queue/summary adapters implementing ports
└── worker/            # (Phase 3) background worker + pipeline
```

Design decisions and their reasons:

1. **`api/` vs `core/` vs `services/` vs `repositories/` are separate top-level folders.**
   This makes the *layers physical*. You can literally see the separation of concerns. A reviewer
   opening the repo understands the architecture in ten seconds. It also lets you enforce import
   rules per-folder (e.g. "services must not import repositories").

2. **`core/ports/` is a folder inside `core/`, isolated from adapters.**
   Ports are the contract; they must not depend on any concrete tech. Putting them in their own
   package with a docstring that says "MUST NOT import concrete adapters" makes the boundary
   obvious and hard to violate by accident.

3. **`core/container.py` is the *only* place that knows concrete classes.**
   This is the composition root. When someone asks "how do I swap Postgres for MySQL?", the answer
   is "write a new repo class, change one line in `container.py`." Centralizing wiring is what makes
   that true. Scattering `TicketRepository()` constructor calls across the codebase would destroy it.

4. **`models/` (ORM) is separate from `schemas/` (Pydantic DTOs — arrives in Phase 1).**
   These are two *different* representations of a ticket:
   - `models/` = how a ticket is stored (DB columns, constraints).
   - `schemas/` = how a ticket enters/leaves the API (validation, JSON shape).
   Keeping them apart means a DB change doesn't automatically change your public API contract, and
   vice versa. Conflating them (one class for both) is a classic junior mistake that couples your
   storage to your wire format.

5. **`worker/` is its own folder.**
   The background processor is a *separate process* from the API (different entrypoint, run in a
   different container in Phase 3). Its own folder reflects that runtime separation.

6. **`__init__.py` in every package** — each contains a one-line docstring describing the package's
   role. Not decorative: it turns the folder into an importable package and documents intent at the
   package level.

---

## 4. File-by-file: what it does and the "why"

### `pyproject.toml`
- **Does:** declares deps (FastAPI, SQLAlchemy, Alembic, psycopg, pydantic-settings) and configures
  ruff (lint), mypy (types), pytest (tests) in one place.
- **Why these choices:** FastAPI for typed APIs + free OpenAPI; SQLAlchemy 2.0 for a typed ORM;
  psycopg v3 as the modern Postgres driver; `strict` mypy because the brief rewards type safety.

### `core/config.py`
- **Does:** a `Settings` class (pydantic-settings) that reads env vars into a *typed, validated*
  object. `get_settings()` is cached so it's read once per process.
- **Why:** centralizes configuration (12-factor). No `os.environ` scattered around. If a required
  var is malformed, you find out at startup, not deep in a request. `Literal["local","dev",...]`
  means an invalid environment name is a startup error, not a silent bug.

### `core/logging.py`
- **Does:** JSON log formatter + a `ContextVar` holding the current request id, so every log line in
  a request is auto-tagged with `request_id`.
- **Why JSON:** machine-parseable logs are the norm in production (searchable in log tools).
- **Why `ContextVar`:** it lets logs include the request id *without* passing the id into every
  function. The middleware sets it once per request; the formatter reads it. Clean correlation.

### `core/response.py`
- **Does:** the `Envelope` model with `ok()` and `fail()` builders + an `ErrorDetail` shape.
- **Why one envelope:** every response — success or error — has the same top-level shape
  (`success/message/data/error/meta`). Clients write one parser. This is the **Builder pattern**:
  `Envelope.ok(data=...)` reads clearly and prevents malformed responses.

### `core/errors.py`
- **Does:** `AppError` base + subclasses (`NotFoundError`→404, `ValidationError`→422,
  `ConflictError`→409, `InvalidTransitionError`→409) and FastAPI handlers that convert *any* error
  into the envelope.
- **Why typed exceptions:** services raise `NotFoundError("ticket 5 not found")` — a *domain*
  concept — instead of knowing about HTTP 404. The handler is the *only* place that maps domain
  errors → HTTP codes. Services stay HTTP-agnostic (which is why they're testable and reusable).
- **Why a catch-all `Exception` handler:** guarantees even an unexpected crash returns the envelope
  (never a raw stack trace leaking to the client), and logs the full trace server-side.

### `models/base.py`
- **Does:** the SQLAlchemy `DeclarativeBase` and a `TimestampMixin` (created_at/updated_at managed
  by the DB via `server_default`/`onupdate`).
- **Why a mixin:** every table needs audit timestamps; a mixin avoids repeating those columns and
  guarantees consistency. DB-managed timestamps (not Python-set) are correct even if multiple
  processes write.

### `core/db.py`
- **Does:** creates the engine + session factory from settings, exposes `session_scope()`
  (a transactional Unit-of-Work), `get_session()` (FastAPI dependency), and `check_database()`.
- **Why `session_scope` (Unit of Work):** it wraps a block in a transaction — commit on success,
  rollback on any exception. The *service* owns the transaction boundary, so "insert ticket + insert
  event" either both happen or neither does. Repos don't manage transactions; that keeps them simple.
- **Why `pool_pre_ping=True`:** silently reconnects dead pooled connections (e.g. after the DB
  restarts), avoiding random "connection closed" errors.

### `core/ports/*.py`
- **Does:** `TicketRepository`, `TicketEventRepository`, `TaskQueue`, `SummaryProvider` as
  `Protocol`s (structural interfaces).
- **Why `Protocol` (not ABC):** Python `Protocol` gives duck-typed interfaces — an adapter satisfies
  it just by having the right methods, no explicit inheritance needed. Great for swappability and
  for test fakes. `@runtime_checkable` lets you `isinstance`-check if desired.
- **Why `Any` placeholders now:** the concrete domain types (Ticket entity, filter DTOs) don't exist
  until Phase 1. Rather than import non-existent modules, the ports use `Any` and a note; they get
  tightened in Phase 1. This keeps the boundary present from day one without a broken import.

### `core/container.py`
- **Does:** a `Container` dataclass + `build_container()`/`get_container()`. Currently holds only
  settings.
- **Why it exists already:** to establish the composition-root habit from the start. In Phase 2/3 it
  will construct the SQLAlchemy repos and the RQ queue and hand them to services. One place, one line
  to swap a backend.

### `api/middleware.py`
- **Does:** `RequestIDMiddleware` — reuse inbound `X-Request-ID` or generate one; set it in the log
  context; echo it on the response.
- **Why:** distributed tracing/debugging. When something fails, the client's `x-request-id` lets you
  grep every log line for that exact request. Reusing an inbound id means the id survives across
  service hops.

### `api/health.py`
- **Does:** `GET /health` returning the envelope with DB status; 200 if up, 503 if down.
- **Why it's the walking-skeleton endpoint:** it exercises the *entire* stack — routing → response
  envelope → config → DB connectivity — in one trivial call. If `/health` works in Docker, the
  plumbing is proven and every later feature builds on solid ground.

### `app/main.py`
- **Does:** `create_app()` factory + `lifespan`. Startup: configure logging → build container →
  init DB engine → verify DB. Shutdown: dispose the engine pool. Wires middleware, handlers, routers.
- **Why a factory function (not a module-level `app` only):** `create_app()` can be called with test
  settings to build an isolated app in tests. The module-level `app = create_app()` at the bottom is
  what Uvicorn imports in production. Best of both.
- **Why `lifespan`:** the modern FastAPI way to run startup/shutdown code. Verifying the DB at
  startup means misconfiguration surfaces immediately; disposing the pool at shutdown avoids leaked
  connections.

### `Dockerfile`
- **Does:** builds a slim Python 3.12 image; installs deps *before* copying source (layer caching);
  runs Uvicorn.
- **Why deps-before-source:** Docker caches layers. Copying `pyproject.toml` and installing first
  means editing your code doesn't reinstall dependencies — much faster rebuilds.
- **Why env vars for unbuffered/no-pyc:** cleaner logs (unbuffered stdout) and no `.pyc` clutter.

### `docker-compose.yml`
- **Does:** defines `db` (postgres, with a healthcheck) and `api` (built from the Dockerfile),
  wires the API to the DB via `DATABASE_URL`, and makes `api` wait for `db` to be *healthy*.
- **Why the healthcheck + `depends_on: condition: service_healthy`:** without it, the API can start
  before Postgres is ready and crash. The healthcheck makes "one command up" actually reliable.
- **Why a named volume (`pgdata`):** data survives `docker compose down` so you don't lose your DB
  between runs.

### `.env.example` / `README.md`
- **Does:** documents every env var and how to run.
- **Why `.example` (not `.env`):** you commit the *template*, never real values/secrets. `.gitignore`
  blocks the real `.env`. This is how you share config shape without leaking credentials.

---

## 5. Patterns you can name in the interview

When they ask "what patterns did you use?", here's your cheat sheet with the file to point at:

| Pattern | Where | One-line justification |
|---------|-------|------------------------|
| Ports & Adapters (Hexagonal) | `core/ports/` + adapters | Business logic depends on interfaces, not tech. |
| Dependency Inversion (the "D" in SOLID) | ports + `container.py` | High-level code doesn't depend on low-level details. |
| Dependency Injection | `container.py` + FastAPI `Depends` | Dependencies are provided, not constructed inline. |
| Composition Root | `container.py` | One place wires concrete → abstract. |
| Builder | `response.py` (`Envelope.ok/fail`) | Fluent, safe object construction. |
| Unit of Work | `db.py` (`session_scope`) | Atomic transaction boundary owned by the service. |
| Repository (interface now, impl Phase 2) | `ports/ticket_repository.py` | Abstracts data access from domain. |
| Application Factory | `main.py` (`create_app`) | Configurable app construction; test-friendly. |
| Middleware / Interceptor | `api/middleware.py` | Cross-cutting request-id handling. |

---

## 6. Questions to test your own understanding

Try answering these without looking (answers are all above):

1. Why is `config.py` built before `db.py`?
2. If you wanted to move from Postgres to MongoDB, which files change — and which absolutely
   must *not* change?
3. Why do services raise `NotFoundError` instead of returning a 404 directly?
4. What breaks if you delete the healthcheck from `docker-compose.yml`?
5. Why are `models/` (ORM) and `schemas/` (DTOs) separate, when both describe a "ticket"?
6. Why build the `ports/` interfaces before the SQLAlchemy repositories?
7. What is a "composition root" and which file is it here?

If you can answer all seven, you understand Phase 0 at the level the interviewer is probing for.

---

## 7. Appendix — `pyproject.toml`, lockfiles, and when they're read

### When is `pyproject.toml` actually read?

At **build/install time**, never at runtime.

```
BUILD/INSTALL TIME                     RUN TIME
──────────────────                     ────────
uv / pip reads pyproject.toml   →       Uvicorn imports app.main:app
   resolves + installs deps     →       Python imports already-installed libs
   (job is DONE)                        (pyproject.toml is never opened again)
```

- **In Docker:** `COPY pyproject.toml uv.lock ./` then `RUN uv sync --frozen` installs the deps into
  the image. Later `CMD uvicorn app.main:app` just runs — it imports libraries that are already
  installed. The manifest is not consulted at runtime.
- **Why copy the manifest before the source?** Docker layer caching. Deps change rarely, code changes
  constantly. Installing deps *before* copying `app/` means editing code reuses the cached install
  layer → rebuilds take ~1s instead of reinstalling everything.
- **The `[tool.*]` sections** (`ruff`, `mypy`, `pytest`) are read only when *you* run those tools,
  not by the app.

### Is it just like `requirements.txt`?

It's a **superset**. `requirements.txt` only lists packages. `pyproject.toml` also carries project
metadata, makes your own code an installable package, supports optional dependency groups (e.g.
`dev`), and holds tool config — replacing `setup.py` + `requirements-dev.txt` + `.ruff.toml` +
`mypy.ini` + `pytest.ini` with one standard file.

### Abstract deps vs the lockfile

- `pyproject.toml` holds **abstract** ranges: `fastapi>=0.115` = "what I want."
- `uv.lock` holds **exact** pins for *every* package incl. transitive ones: `fastapi==0.141.1` +
  its sub-dependencies = "what I actually get, reproducibly."

```
pyproject.toml          uv lock            uv.lock
"fastapi>=0.115"  ──►  resolve + pin  ──►  fastapi==0.141.1 (+ all sub-deps, exact)
(human-friendly)                           (machine-exact, committed to git)
```

You edit `pyproject.toml` by hand; you **regenerate** `uv.lock` with `uv lock` whenever deps change;
you **commit** the lock so your laptop, CI, and the reviewer's `docker build` all install identical
versions. The Docker build uses `uv sync --frozen` — the `--frozen` flag makes the build *fail* if
the lock is out of date, guaranteeing the image matches the committed lockfile.

**Interview soundbite:** *"`pyproject.toml` declares abstract dependencies and tool config; `uv.lock`
pins exact versions of the full transitive tree for reproducible builds. Docker installs from the
frozen lock so images are deterministic."*

---

## 8. Appendix — Local dev environment must mirror Docker (Python version + packages)

### The problem

Your IDE gives correct feedback only if it points at the **same Python version + same installed
packages** that run in production (Docker). If the IDE uses a random system Python (e.g. 3.14) with
no project packages:

- **Autocomplete breaks** — it can't find `fastapi`/`sqlalchemy`, so no suggestions, "unresolved
  import" everywhere.
- **Type-checking lies** — false errors that don't exist at runtime, or real errors missed.
- **Version drift** — a 3.13-only syntax the IDE allows will crash in the 3.12 container; a 3.12
  feature may be flagged invalid if the IDE thinks you're on an older version.

**The runtime is the source of truth. Local must mirror it.**

### The fix (uv-managed `.venv` pinned to 3.12)

```bash
uv sync --python 3.12 --extra dev   # create .venv on Python 3.12 with EXACT locked deps + dev tools
```

- `--python 3.12` → matches `python:3.12-slim` in the Dockerfile.
- exact deps come from `uv.lock` → matches the image's installed packages.
- `--extra dev` → also installs ruff/mypy/pytest locally so you lint/type-check/test the same way CI does.

Then point the IDE at `.venv/bin/python`. Now local autocomplete, imports, linting, and typing all
match the container.

### What makes this automatic for anyone who opens the project

| File | Role | Committed? |
|------|------|-----------|
| `.python-version` (`3.12`) | tells uv (and pyenv) which Python to use | ✅ yes |
| `.vscode/settings.json` | points IDE at `.venv`, enables ruff + Pylance | ✅ yes (whitelisted in `.gitignore`) |
| `.vscode/extensions.json` | recommends Python + Ruff extensions | ✅ yes |
| `.venv/` | the actual environment | ❌ **never commit** (gitignored; regenerated via `uv sync`) |

> Note the `.gitignore` trick: we ignore `.vscode/*` but *un-ignore* `settings.json` and
> `extensions.json` with `!`. That shares the project's IDE config without committing machine-specific
> editor state — and never commits `.venv` (which is large and OS-specific).

### The guarantee

```
Dockerfile:  python:3.12-slim + uv sync --frozen (from uv.lock)
                         ║  same Python, same exact packages
Local:       .venv on 3.12 + uv sync (from uv.lock)
```

Because both install from the *same* `uv.lock` on the *same* Python minor version, "works on my
machine" and "works in Docker" become the same statement. Running `uv run ruff check app` and
`uv run mypy app` locally reproduces CI exactly.

**Interview soundbite:** *"I pin the Python version in both the Dockerfile and a local uv venv, and
both install from the same lockfile — so my IDE's type-checking and autocomplete reflect precisely
what runs in the container. No environment drift."*

---

## 9. Appendix — `uv sync --python 3.12 --extra dev` explained

**Plain English:** "Create/update a local `.venv` on Python 3.12 and install exactly the packages
in `uv.lock` — including the optional `dev` tools."

### Piece by piece

- **`uv sync`** — makes the `.venv` match the lockfile *exactly*. It creates `.venv/` if missing,
  reads `uv.lock`, and installs/**removes** packages until the venv contains precisely what the lock
  says. Unlike `pip install` (which only adds), `uv sync` is *declarative*: the env can never drift
  from the committed lock.
- **`--python 3.12`** — which interpreter to build the venv on. Forces 3.12 to match
  `python:3.12-slim` in the Dockerfile (without it, uv might pick a different system Python).
- **`--extra dev`** — also install the optional dependency group `dev` from `pyproject.toml`
  (ruff, mypy, pytest, httpx). These are dev-only tools, not needed at runtime.

```toml
[project]
dependencies = [ "fastapi", "sqlalchemy", ... ]   # always installed
[project.optional-dependencies]
dev = [ "ruff", "mypy", "pytest", "httpx" ]        # only with --extra dev
```

### Local vs Docker (same lock, different extras)

| Command | Python | Installs | Used by |
|---------|--------|----------|---------|
| `uv sync --python 3.12 --extra dev` | 3.12 | runtime deps **+ dev tools** | you, locally |
| `uv sync --frozen --no-dev` (Dockerfile) | 3.12 (base image) | runtime deps **only** | the container |

Both install from the **same `uv.lock`** on the **same 3.12** → identical versions. Local just
additionally has the dev tools; the production image stays lean.

### Why not `pip install`?

`pip install` only adds packages and doesn't enforce the lock, so environments drift over time.
`uv sync` guarantees the venv is always an exact mirror of `uv.lock` — run it anytime for a clean,
correct environment.

**One-liner:** *"build my local venv on Python 3.12 with the exact locked deps plus dev tools, so my
machine matches Docker and I can lint/type-check/test the same way CI does."*
