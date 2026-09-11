# Learning: Migrations in Production (the big one)

> A standalone deep-dive on how database migrations really work in production: the migration
> lifecycle, generate-vs-apply, reproducibility, safe schema changes on high-traffic tables, and
> expand/contract sequencing. This is senior/DBA-level material and a common interview topic.

---

## 1. Migration vs ORM — two different jobs

- **Migration (Alembic)** — changes the *table structure* (DDL). Runs **once at deploy**, before the
  app serves traffic. Not part of request handling.
- **ORM (SQLAlchemy)** — reads/writes *rows* (DML). Runs on **every request**.

Tables must exist (migration) before the app can use them (ORM).

---

## 2. Generate ≠ Apply (the most misunderstood part)

Two different commands, different time/place/person:

| Command | Does | Who / where | When |
|---------|------|-------------|------|
| `alembic revision --autogenerate` | **creates** a migration *file* | developer, **locally** | while coding a change |
| `alembic upgrade head` | **applies** existing files to the DB | deploy/entrypoint (**Docker**) | at deploy time |

**Docker only ever runs `upgrade`. It never generates files.** So migration files are NOT created
inside the container — they're authored locally and shipped in the image.

### The workflow
```
LAPTOP (dev)
1. edit model (add column)
2. uv run alembic revision --autogenerate -m "add col"   → creates versions/xxx.py ON DISK
3. review + fix the file (autogenerate is often imperfect — enums, indexes, renames)
4. git add + commit the migration file  (it is SOURCE CODE)
        │
BUILD:  docker build → COPY alembic ./alembic  (committed file goes INTO the image)
        │
DEPLOY: entrypoint runs `alembic upgrade head` → applies xxx.py that was baked into the image
```

### Why generation must be local, never in Docker
1. **Autogenerate isn't always correct** — it diffs models vs DB and guesses DDL; a human must
   review/edit (we hit this with the enum roundtrip bug). You can't review a file a container made
   and threw away.
2. **Determinism** — every environment (CI, staging, prod) must apply the *same* files in the *same*
   order. Committing freezes them as the single source of truth.
3. **Container files are ephemeral** — anything written in a container is lost on destroy. That's
   exactly why you never author migrations there.

**Mental model:** a migration file is source code. You write/review/commit it; the server *runs* it.
You'd never expect a prod server to *write* new source for you.

---

## 3. Migrations don't auto-run — you must wire it

Our Dockerfile `CMD` only starts uvicorn. Automatic migration on startup is something you add
explicitly, typically an entrypoint:
```sh
alembic upgrade head        # 1. bring schema to latest (idempotent)
[ "$ENVIRONMENT" = local ] && python -m scripts.seed   # 2. seed ONLY in dev
uvicorn app.main:app        # 3. serve
```
`alembic upgrade head` is **idempotent** — it checks the `alembic_version` table and runs only what's
missing. Safe to run on every startup.

> Seeding is dev-only. Never seed fake data into production. Gate it behind `ENVIRONMENT`.

---

## 4. What "remembers" the schema state, and container/DB lifecycle

The `alembic_version` table (one row, current revision id) lives **inside the DB** and records what's
applied.

| Event | Effect |
|-------|--------|
| App container restart, **volume kept** (`docker compose down`) | `alembic_version` intact → `upgrade` = **no-op**, data intact |
| Volume deleted (`docker compose down -v`) / brand-new DB | no `alembic_version` → `upgrade` runs **everything**, seed re-inserts |
| Prod deploy, **new** migration present | `alembic_version` behind → applies only the new steps |
| Prod deploy, **no** new migration | `alembic_version` at head → **no-op**, data untouched |

Key point: migrations re-run because the **data** was wiped, not because the container restarted.
Kill the app container 100×; if the Postgres volume survives, `upgrade` is a no-op.

---

## 5. Reproducibility — same versions everywhere or migrations break

Migrations are version-sensitive: different Alembic/SQLAlchemy versions can emit different DDL, and
migration files call `sqlalchemy as sa` APIs directly. Version drift → different SQL or broken files.

What must match between where you **generate** and where you **apply**:

| Must match | Guaranteed by |
|-----------|---------------|
| Alembic version | `uv.lock` |
| **SQLAlchemy version** (bigger risk than Alembic) | `uv.lock` |
| DB driver (psycopg) | `uv.lock` |
| Target **Postgres** version | Docker image tag (`postgres:16-alpine`) |
| Python version | `.python-version` + `python:3.12-slim` |

Because local `.venv` (via `uv sync`) and the Docker image (via `uv sync --frozen`) install from the
**same committed `uv.lock`**, `uv run alembic ...` locally and `alembic upgrade head` in the container
use **identical** Alembic + SQLAlchemy + driver versions. `--no-dev` only omits dev tools (ruff/mypy),
never changes runtime pins. Pin Postgres + Python too → fully reproducible migrations.

---

## 6. Safe schema changes on a BIG, high-traffic table

### The core danger: `ALTER TABLE` takes an ACCESS EXCLUSIVE lock
That lock blocks **all reads and writes** on the table. The only question is **how long** it's held.

### Fast (metadata-only) vs slow (table rewrite)
| Operation | Lock impact | Safe on hot table? |
|-----------|-------------|--------------------|
| Add **nullable** column, no default | metadata only, ms | ✅ |
| Add column with **constant** default (PG 11+) | metadata only, ms | ✅ |
| Add **NOT NULL** column directly | full scan/rewrite under ACCESS EXCLUSIVE | ❌ |
| **Change column type** | full rewrite | ❌ (use new column + backfill) |
| Add index normally | blocks writes during build | ❌ use `CREATE INDEX CONCURRENTLY` |
| NOT NULL via `NOT VALID` + `VALIDATE` | short locks only | ✅ |
| Huge single `UPDATE` backfill | long lock + table bloat | ❌ batch it |

### What happens if you deploy a blocking ALTER naively
The migration grabs ACCESS EXCLUSIVE and rewrites every row → new reads/writes **block** → requests
time out → DB pool fills → cascading failures. Worst case: the migration waits behind a long-running
query while itself blocking all new queries → **lock queue pileup** → outage.

### The safe playbook to add a column that needs values
1. **Add nullable, no default** (instant, metadata-only): `ALTER TABLE tickets ADD COLUMN note TEXT;`
2. **Backfill in batches** (small transactions, pauses) — never one giant `UPDATE`.
3. **Add default for future rows** (fast PG 11+): `ALTER COLUMN note SET DEFAULT '';`
4. **Add NOT NULL without a long lock:**
   `ADD CONSTRAINT ck CHECK (note IS NOT NULL) NOT VALID;` (instant) then
   `VALIDATE CONSTRAINT ck;` (scans under a weaker SHARE lock — doesn't block writes).

### Two operational safeguards every senior adds
- **`SET lock_timeout = '3s';`** before the ALTER → migration **fails fast and retries** instead of
  silently queueing behind a long query and taking the table down.
- **`CREATE INDEX CONCURRENTLY`** for indexes on hot tables (no write blocking; can't run inside a
  transaction, so Alembic needs special handling).

---

## 7. Expand / Contract (parallel change) — ordering code vs schema

During a **rolling deploy**, old and new app versions run **simultaneously**, and the migration runs
somewhere in that window. Every schema state must be compatible with **both** versions.

### Adding a column (EXPAND) — schema first, then code
```
Release 1 (schema): model + migration committed together → deploy → column exists (nullable, unused)
                    old pods ignore it (nullable) ✅   new pods don't depend on it yet ✅
Release 2 (code):   deploy code that reads/writes the column → safe, column already exists ✅
(optional) Release 3: backfill in batches, then tighten (NOT NULL via NOT VALID + VALIDATE)
```
Why two releases: prevents the race where **new code that needs the column starts before the
migration finishes** → missing-column 500s. By Release 2 the column definitely exists.

> Clarification: the **model change and the migration file are one unit** (both describe the schema)
> committed and deployed together as "the schema release." The *column-using code* is the separate
> second release. For simple nullable adds, teams sometimes combine them in one release IF the
> migrate step is guaranteed to finish before new pods take traffic — but the two-release expand is
> the bulletproof, general answer.

### Removing a column (CONTRACT) — code first, then schema (mirror image)
```
Release 1 (code):   deploy code that STOPS using the column
Release 2 (schema): migration DROPS the column
```
Drop-first would crash old pods still referencing it.

### The one rule
> **Expand before contract. Add = schema first, code second. Remove = code first, schema second.**
> Every schema state must be compatible with both the running code and the code being deployed.

---

## 7b. Where should migrations run? (app-startup vs dedicated step vs manual)

Three approaches, with tradeoffs:

| Approach | Pros | Cons |
|----------|------|------|
| **1. App serve-startup** (entrypoint runs `upgrade` then uvicorn) | simplest "one command up" | **runs on every replica → races**; couples serving with schema change; a bad migration blocks app start |
| **2. Dedicated one-shot step** (init-container / K8s Job / pipeline stage / compose `migrate` service) | **runs exactly once**; fails before app rolls out; natural place for approvals + `lock_timeout` | a little more infra config |
| **3. Fully manual** (human runs from a bastion/terminal) | max control for big/risky migrations; run at low-traffic | error-prone, forgettable, doesn't scale |

**The killer problem with Approach 1 in production:** with N API replicas, all N run
`alembic upgrade head` simultaneously on deploy → lock contention on `alembic_version`, possible
partial/confused state. A dedicated one-shot job runs it a **single time**, then app pods start
against an already-current schema.

**Recommendation:** production → **Approach 2** (dedicated pre-deploy step, not per-replica app
startup, not manual). For very large/risky migrations, combine with a manual/approved window.

**What this project does:** a separate **`migrate` compose service** runs
`alembic upgrade head` (and seeds only in local/dev), exits, and the `api` service uses
`depends_on: { migrate: { condition: service_completed_successfully } }` so the API starts only
after migrations succeed. This mirrors the production one-shot-job pattern while keeping a single
`docker compose up`. Verified: migrate runs once → exits(0) → api starts; on restart with the volume
kept, migrate is a no-op (0 rows seeded, no schema change).

```yaml
migrate:
  build: .
  command: ["sh", "scripts/migrate.sh"]   # alembic upgrade head; seed if local/dev; exit
  depends_on: { db: { condition: service_healthy } }
api:
  depends_on:
    db: { condition: service_healthy }
    migrate: { condition: service_completed_successfully }
```

> One-liner: *don't migrate in the app's serve-startup in prod (per-replica races) and don't rely on
> humans (forgettable) — run migrations as a dedicated one-shot step before the app rolls out;
> locally a `migrate` service the API depends on mirrors that.*

## 8. Interview soundbites

- *"Generate migrations locally, review them, commit them — they're source code. Docker only
  applies (`upgrade`), never generates."*
- *"`alembic upgrade head` is idempotent via the `alembic_version` table, so it's safe on every
  deploy; it's a no-op when there's nothing new."*
- *"`uv.lock` pins Alembic + SQLAlchemy + driver identically local and in Docker, so migration
  generation and application are reproducible; I also pin Postgres and Python."*
- *"On a hot table I never run a blocking ALTER in one shot. Add the column nullable (metadata-only),
  backfill in batches, add NOT NULL via NOT VALID + VALIDATE, set `lock_timeout` so the migration
  fails fast instead of queueing behind long queries, and build indexes CONCURRENTLY."*
- *"I sequence with expand/contract: for adds, schema first then code; for drops, code first then
  schema — because during a rolling deploy old and new code run at once."*

---

## 9. Self-test

1. Which Alembic command runs in Docker, and which never does?
2. Why must migration files be committed to git rather than generated in the container?
3. You restart the app container but keep the volume — does `upgrade` re-run migrations? Why?
4. Why can a mismatched SQLAlchemy version (not just Alembic) break a migration?
5. Why does `ADD COLUMN x TEXT` differ from `ADD COLUMN x TEXT NOT NULL` on a huge table?
6. What does `lock_timeout` protect you from during a migration?
7. For adding a column: does schema or code deploy first? For removing one?
8. What is `alembic_version` and where does it live?
