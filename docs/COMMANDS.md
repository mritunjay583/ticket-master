# Commands — Running & End-to-End Testing

Quick reference for running the stack, opening shells into each service, and shutting down (with or
without wiping data). Run all commands from the `ticket-master/` directory.

**Service names** (used by `docker compose`): `db`, `redis`, `migrate`, `api`, `worker`.

---

## 1. Start the app

### First run / after code changes (build the image)
```bash
docker compose up --build
```

### Start detached (background)
```bash
docker compose up --build -d
```

> Only `api` has `build: .`; `migrate` and `worker` reuse the built `ticket-master-api` image. So the
> `--build` on first run is required — it builds that shared image. After it exists, plain
> `docker compose up` works.

### Startup order (automatic)
1. `db` (Postgres) → healthy
2. `redis` → healthy
3. `migrate` (one-shot) → `alembic upgrade head` + seed (local/dev) → **exits 0**
4. `api` → starts after migrate succeeds → http://localhost:8000
5. `worker` → starts consuming jobs + runs the sweeper

### Check status
```bash
docker compose ps -a                 # all services incl. the exited migrate
```

### View logs (api & worker)
```bash
# Follow live (like tail -f). Ctrl+C stops the view, not the container.
docker compose logs -f api                 # API: requests, startup
docker compose logs -f worker              # worker: process_ticket + sweeper
docker compose logs -f api worker          # both, interleaved & color-coded
docker compose logs -f                     # ALL services

# Last N lines (no follow)
docker compose logs --tail 50 worker
docker compose logs --tail 50 api

# With timestamps / since a time window
docker compose logs -t worker
docker compose logs -f --since 5m worker

# migrate ran once and exited — view its migration + seed output
docker compose logs migrate

# Filter (our logs are structured JSON, so grep works well)
docker compose logs worker | grep process_ticket    # each job processed
docker compose logs worker | grep sweeper            # sweeper runs
docker compose logs api    | grep request_id         # trace by correlation id
```

> If you started in the foreground (`docker compose up` without `-d`), logs already stream in that
> terminal — the `logs -f` commands above are mainly for when you started detached (`-d`).

### Quick health check
```bash
curl -i http://localhost:8000/health
# Swagger UI: http://localhost:8000/docs
```

---

## 2. Open a shell into each service

### Postgres (psql)
```bash
docker compose exec db psql -U ticketmaster -d ticketmaster
```
Useful once inside psql:
```sql
\dt                      -- list tables
\d tickets               -- describe the tickets table
SELECT id, status, priority, department, processing_status FROM tickets LIMIT 10;
SELECT typname FROM pg_type WHERE typtype='e';   -- list enum types
SELECT version_num FROM alembic_version;         -- current migration
\q                       -- quit
```
One-off query without entering the shell:
```bash
docker compose exec db psql -U ticketmaster -d ticketmaster -c "SELECT count(*) FROM tickets;"
```

### Redis (redis-cli)
```bash
docker compose exec redis redis-cli
```
Useful once inside:
```
PING                     -- -> PONG
KEYS *                   -- see RQ keys (queues, jobs, registries)
LLEN rq:queue:tickets    -- pending jobs in the queue
FLUSHALL                 -- wipe Redis (simulate a lost queue; sweeper will recover)
exit
```
One-off:
```bash
docker compose exec redis redis-cli PING
```

### API container (app)
```bash
docker compose exec api sh
```
Inside you can run app tooling (the image has the deps installed):
```bash
alembic current                       # show current migration revision
python -m scripts.seed                # run the seed manually (idempotent)
python -c "from app.core.config import get_settings; print(get_settings())"
exit
```

### Worker container
```bash
docker compose exec worker sh
```
(Same image as `api`, so the same commands work. This is where background jobs run.)

> If `sh` feels bare, `bash` is also available: `docker compose exec api bash`.

---

## 3. Shutdown — two types

### Type 1 — Stop but KEEP data (fast restart, no re-migration)
```bash
docker compose down
```
- Removes containers + network, **keeps the named volumes** (`pgdata`, `redisdata`).
- Next `docker compose up` → the DB still has all tables + data → `alembic upgrade head` is a
  **no-op** (already at head) and the seed creates **0 rows** (data already present).
- Use this for normal day-to-day stop/start.

### Type 2 — Stop and DELETE all data (fresh migration + seed next time)
```bash
docker compose down -v
```
- The `-v` also **removes the named volumes** → Postgres and Redis start empty next time.
- Next `docker compose up` → empty DB → `migrate` runs **all migrations fresh** and **re-seeds**
  (4 agents + 4 tickets); Redis starts with an empty queue.
- Use this for a clean-slate / fresh-install test (what a reviewer experiences on first clone).

> Want to wipe data but keep the built image? `down -v` does exactly that (it only removes volumes,
> not images). To also remove the built image: `docker compose down -v --rmi local`.

---

## 4. End-to-end test walkthrough

```bash
# 0. Clean slate (fresh migrations + seed)
docker compose down -v
docker compose up --build -d

# 1. Wait for startup, confirm services
sleep 15
docker compose ps -a          # migrate should show Exited (0); api + worker Up

# 2. Health + seeded data
curl -s http://localhost:8000/health
curl -s "http://localhost:8000/api/v1/tickets?page=1&page_size=10"   # total should be 4 (seed)

# 3. Create a ticket (async processing kicks in)
curl -s -X POST http://localhost:8000/api/v1/tickets \
  -H 'Content-Type: application/json' \
  -d '{"customer_name":"E2E","customer_email":"e2e@example.com",
       "subject":"App error on login","description":"login failed",
       "priority":"MEDIUM","category":"TECHNICAL"}'
# note the returned "id"

# 4. After a few seconds, fetch it — the worker has processed it
#    processing_status: PENDING -> DONE, priority -> HIGH, department -> ENGINEERING
curl -s http://localhost:8000/api/v1/tickets/<ID_FROM_STEP_3>

# 5. See the audit trail (CREATED then PROCESSED)
curl -s http://localhost:8000/api/v1/tickets/<ID>/events

# 6. Update status (state machine); invalid transition returns 409
curl -s -X PATCH http://localhost:8000/api/v1/tickets/<ID>/status \
  -H 'Content-Type: application/json' -d '{"status":"IN_PROGRESS","actor":"agent@x.com"}'

# 7. Watch the worker doing its job
docker compose logs worker | grep -E "process_ticket|sweeper"

# 8. Tear down (wipe data)
docker compose down -v
```

### Testing the reliability sweeper (recover a lost job)
```bash
# create a ticket, then simulate a lost queue:
docker compose exec redis redis-cli FLUSHALL
# the ticket stays PENDING; within the sweeper interval it is re-enqueued and processed.
docker compose logs worker | grep sweeper      # "sweeper re-enqueued stuck tickets"
```
Tip: for a faster demo, start with short intervals:
```bash
SWEEPER_INTERVAL_SECONDS=5 SWEEPER_STALE_AFTER_SECONDS=3 docker compose up -d worker
```

---

## 5. How the seed works (confirmed)

Flow: the **`migrate` service** runs `scripts/migrate.sh`, which does:
```sh
alembic upgrade head                 # 1. create/upgrade schema
if ENVIRONMENT is local or dev:      # 2. seed only in local/dev (never prod)
    python -m scripts.seed
```

`scripts/seed.py` is **idempotent**:
- Inserts 4 sample **agents** (Alice/Bob/Carol/Dave) — skips any whose `email` already exists.
- Inserts 4 sample **tickets** (across BILLING/TECHNICAL/ACCOUNT/GENERAL, various statuses/priorities)
  — skips any whose `subject` already exists.
- So: on an **empty DB** → creates 4 agents + 4 tickets; on a **populated DB** → creates 0 (no
  duplicates). Safe to run repeatedly.

Consequence for the two shutdowns:
- `docker compose down` (keep data) → next start: seed finds existing rows → **0 created**.
- `docker compose down -v` (wipe data) → next start: empty DB → **4 agents + 4 tickets created**.

Run the seed manually if ever needed:
```bash
docker compose exec api python -m scripts.seed
```

> Note: the seeded tickets are inserted directly (not via the API), so they start with
> `processing_status = PENDING` and are **not** auto-enqueued for processing. They exist for quick
> listing/filtering tests. Tickets created via `POST /api/v1/tickets` are the ones that get
> asynchronously processed. (The sweeper will eventually pick up seeded PENDING tickets too, once
> they pass the stale threshold.)
