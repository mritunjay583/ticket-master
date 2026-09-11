# Phase 5 — Polish & Deliverables (Learning Notes)

> The final phase: no new features — turn a working system into a clean, submittable deliverable.
> This is where "it works on my machine" becomes "a reviewer clones it and it just works," and where
> the assignment's explicit README requirements are satisfied.

---

## 1. Why polish is its own phase (and matters as much as code)

A reviewer's experience is: clone → read README → run one command → poke the API. If any of those
stumbles, the *engineering* underneath barely gets seen. Phase 5 optimizes that first impression:

- **One-command run that actually works from a clean state** (not "works because my DB was already
  migrated").
- **A README that answers every question before it's asked** (overview, architecture, setup, env
  vars, run, API docs, tradeoffs).
- **Presentable API docs** (Swagger with examples).
- **Green checks** (lint, types, tests) — signals discipline.

Senior signal: the submission is *proportional and finished* — complete, documented, no loose ends,
no over-engineering.

---

## 2. What we did

### a) Docs reorganized (Option B)
Moved the 11 `LEARNING_*.md` deep-dives into `docs/learning/`, leaving `docs/ARCHITECTURE.md` and
`docs/IMPLEMENTATION_PLAN.md` as the "official" docs. Why: a work submission should look
professional — the design doc front and center, learning notes clearly separated as optional
reference. Used `git mv` to preserve file history.

### b) OpenAPI / Swagger polish
- Richer app `description` + `openapi_tags` (grouped, described) in the app factory.
- `json_schema_extra` **examples** on `CreateTicketRequest` / `UpdateStatusRequest` so Swagger shows
  realistic payloads ("Try it out" is pre-filled).
- Served at `/docs` (Swagger), `/redoc`, `/openapi.json`.

### c) The comprehensive README
Rewrote it to satisfy the brief's required sections exactly: project overview, architecture
decisions, setup, environment variables, how to run locally, API documentation access, tradeoffs &
assumptions — plus a structure map and a dev section. Kept it skimmable (tables over prose).

### d) Final consistency + quality gate
- `.env.example` documents every variable actually used.
- `ruff` + `mypy` + `pytest` all green (43 tests).
- No stray temp files, no secrets committed.

---

## 3. The fresh-clone smoke test (the real gate)

The one test that matters for "runnable with minimal setup": simulate a brand-new checkout.

```bash
docker compose down -v        # wipe volumes → truly clean state (no leftover DB/Redis data)
docker compose up --build     # one command
```

Then verify what a reviewer verifies:
```
health: 200
swagger /docs: 200
openapi.json: 200
seeded list total: 4                 # migrate service seeded sample data
processed ticket: status=DONE priority=HIGH dept=ENGINEERING   # create → async worker processed it
```

The critical part is `down -v`: without removing volumes you might pass only because your DB was
*already* migrated/seeded from earlier runs. `-v` forces the "first time anyone runs this" path —
migrations must run, seed must load, services must order correctly.

---

## 4. Why `docker compose down -v` matters (subtle but important)

- `docker compose down` — stops and removes containers/networks, **keeps named volumes** (your
  Postgres/Redis data survives).
- `docker compose down -v` — **also removes named volumes** → next `up` starts with empty data.

For a smoke test you want `-v` so you exercise the full cold-start: DB empty → migrate creates
schema + seeds → API/worker start. That's exactly the reviewer's first-run experience.

---

## 5. Deliverables checklist (what the brief asked for)

| Deliverable | Where |
|-------------|-------|
| Source code | `app/` |
| Docker configuration | `Dockerfile`, `docker-compose.yml` |
| Database migrations | `alembic/`, applied by the `migrate` service |
| Seed scripts | `scripts/seed.py` (run by `migrate` in local/dev) |
| README documentation | `README.md` (overview, architecture, setup, env, run, API docs, tradeoffs) |
| Runnable with minimal setup | single `docker compose up --build` |

---

## 6. Interview soundbites

- *"The deliverable runs from a truly clean state — I smoke-test with `docker compose down -v` so I'm
  not fooled by leftover volumes."*
- *"Learning notes are separated into `docs/learning/` so the submission looks professional; the
  design doc and plan are the official docs."*
- *"Swagger has examples and grouped tags — the API is self-documenting via `/docs`."*
- *"Polish is a phase, not an afterthought: the reviewer's first 5 minutes are clone, README, one
  command, poke the API — I optimized exactly that path."*

---

## 7. Self-test
1. Why is `docker compose down -v` (not just `down`) the right way to smoke-test?
2. What are the seven README sections the brief requires?
3. Why move the learning docs into a subfolder for the submission?
4. How does the reviewer see example request payloads without reading the code?
5. What proves "runnable with minimal setup" objectively?
