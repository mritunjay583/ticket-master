# Learning: Phase 4 — Reliability & At-Least-Once Processing

> How we guarantee no ticket is ever permanently unprocessed, even if Redis dies, the worker
> crashes, or the enqueue call fails. Covers the failure modes, the layered defense, retries, the
> sweeper (RQ-scheduled + a standalone-loop alternative), Redis AOF, and the outbox pattern.

---

## 1. The failure modes we're defending against

| Failure | Without hardening | Risk |
|---------|-------------------|------|
| `enqueue` fails (Redis down at create time) | ticket stays PENDING forever | lost work |
| Redis restarts (in-memory) | queued jobs vanish | lost work |
| Worker crashes mid-job | job may be lost | lost work |
| Transient error (DB blip) | job fails, no retry | lost work |

Goal: **at-least-once** — every ticket gets processed at least once; crashes cause *delay*, never *loss*.

---

## 2. The layered defense (defense in depth)

```
Postgres (processing_status = PENDING)      ← source of truth, survives ANY crash
      │
      ├─ Redis AOF persistence               ← survives Redis restart (~1s window)
      ├─ RQ retries + failed-job registry     ← transient errors auto-retry; permanent → DLQ
      └─ Sweeper re-enqueues stuck PENDING     ← catches anything that slipped
              │
              └─ idempotent process_ticket     ← safe to run again, no duplicates
```

Key mental model: **the queue is a fast dispatch mechanism, not the system of record.** As long as
the durable intent lives in Postgres (`processing_status = PENDING`), a Redis/worker crash means the
ticket is processed *later*, never *never*.

---

## 3. Retries with backoff (transient failures)

`app/adapters/queue/rq_task_queue.py`:
```python
retry = Retry(max=self._max_retries, interval=[10, 30, 60][: self._max_retries] or [10])
job = self._queue.enqueue(func, *args, retry=retry, **kwargs)
```
- A job that raises is retried up to `JOB_MAX_RETRIES` times with increasing delay (10s, 30s, 60s).
- Handles transient issues (temporary DB/network blips) automatically.
- A job that exhausts retries lands in RQ's **failed-job registry** (the dead-letter equivalent) —
  inspectable, not silently lost.

---

## 4. The sweeper (the core safety net)

`app/worker/sweeper.py` — `sweep_pending_tickets()` finds tickets stuck in PENDING older than a
threshold and re-enqueues them:
```python
cutoff = now() - timedelta(seconds=settings.sweeper_stale_after_seconds)
stuck = select(Ticket.id).where(
    Ticket.processing_status == PENDING, Ticket.created_at < cutoff
).limit(batch_size)
for ticket_id in stuck:
    queue.enqueue(process_ticket, str(ticket_id))
```
This is what makes **Postgres the source of truth**: it catches enqueue failures, Redis wipes, and
anything else. Combined with the **idempotent** `process_ticket` (DONE guard + upsert), re-enqueuing
is always safe.

### Verified end-to-end
We created a ticket (PENDING), **flushed Redis** to simulate a totally lost job, then started the
worker. The sweeper logged `re-enqueued stuck tickets, count: N` and every ticket then reached
`processing_status = DONE` — jobs lost from Redis were fully recovered from Postgres.

---

## 5. Scheduling the sweeper — two approaches

### Approach A (what we use): RQ scheduled + self-rescheduling recurring job
`worker.py` calls `schedule_sweeper()` on startup; the job re-schedules itself at the end of each run:
```python
# app/worker/sweeper.py
def run_sweeper_cycle() -> None:
    try:
        sweep_pending_tickets()
    finally:
        queue.enqueue_in(timedelta(seconds=interval), run_sweeper_cycle, job_id=SWEEPER_JOB_ID)
```
`worker.work(with_scheduler=True)` runs RQ's scheduler in the same process, so scheduled jobs fire
without a separate scheduler daemon. A fixed `job_id` prevents duplicate schedules stacking on
restart.

> **Gotcha we hit:** RQ raises *"Functions from the `__main__` module cannot be processed by
> workers"*. The scheduled function must be importable by a stable path, so it lives in
> `app.worker.sweeper` (NOT in the `worker.py` entrypoint which runs as `__main__`).

### Approach B (alternative): a standalone periodic loop in the worker
Instead of scheduling a job, run a plain background thread/loop that calls the sweep on an interval.
No RQ scheduler involved:

```python
# sketch — a standalone sweeper loop (e.g. in a separate process/container or a worker thread)
import time
from app.core.config import get_settings
from app.core.db import init_engine
from app.worker.sweeper import sweep_pending_tickets

def run_sweeper_loop() -> None:
    settings = get_settings()
    init_engine(settings)
    while True:
        try:
            sweep_pending_tickets()
        except Exception:
            logger.exception("sweeper cycle failed")   # never let the loop die
        time.sleep(settings.sweeper_interval_seconds)

if __name__ == "__main__":
    run_sweeper_loop()
```
Run it as its own compose service: `command: ["python", "-m", "app.worker.sweeper_loop"]`.

| | A: RQ scheduled job | B: standalone loop |
|--|--------------------|--------------------|
| Infra | reuses the worker + RQ scheduler | a separate long-running process/thread |
| Visibility | shows up as RQ jobs (nice for monitoring) | just logs |
| Simplicity | needs stable import path (the `__main__` gotcha) | dead simple `while True: sleep` |
| Multiple workers | RQ scheduler lock ensures one scheduler | you must ensure only ONE loop runs (else duplicate sweeps) |
| Best when | you already run RQ workers | you want a dedicated, independent sweeper cron |

Both are valid. A is tidy when you already have RQ; B (or a real cron / Kubernetes CronJob) is
common in production for a clearly-separated, independently-scaled sweeper.

> In a bigger system you'd often use a **Kubernetes CronJob** or **Celery beat** for the periodic
> trigger instead of a self-rescheduling job — same idea, external scheduler.

---

## 6. Redis AOF persistence

`docker-compose.yml`:
```yaml
redis:
  command: ["redis-server", "--appendonly", "yes", "--appendfsync", "everysec"]
  volumes: [ "redisdata:/data" ]
```
- **AOF (append-only file):** Redis logs every write; on restart it replays the log.
- `everysec` fsync → at most ~1 second of writes lost on a crash (good durability/perf balance).
- Shrinks the "Redis crashed" data-loss window from *everything* to *~1s* — and the sweeper covers
  even that.

---

## 7. Worker-crash handling

- RQ tracks in-flight jobs in a `StartedJobRegistry`; a job whose worker died can be detected and
  requeued, and a **job timeout** prevents a hung job blocking forever.
- Because `process_ticket` is **idempotent**, requeuing after a mid-job crash is safe (no duplicate
  `ProcessingResult`, guarded by `processing_status`).

---

## 8. The Transactional Outbox (the production-grade evolution)

Our `processing_status = PENDING` + sweeper is a **pragmatic outbox**. The full pattern:

```
BEGIN;
  INSERT INTO tickets (...);
  INSERT INTO outbox (event_type='ticket.created', ticket_id, status='PENDING');
COMMIT;                      ← ticket + intent committed atomically
-- a relay polls outbox WHERE status='PENDING' → publishes to the queue → marks DISPATCHED
```
- Guarantees it's **impossible** to have a ticket without its pending job (same transaction).
- The relay is the only thing that talks to the broker; if the broker is down, rows stay PENDING and
  are retried.
- Our version collapses "outbox row" into the ticket's own `processing_status` column, and the
  sweeper *is* the relay. Enough for this scale; the dedicated outbox table is the next step at higher
  scale or when many event types are published.

---

## 9. Interview soundbites

- *"At-least-once via defense in depth: Postgres PENDING is the source of truth; Redis AOF, RQ
  retries, and a sweeper are layers on top; the job is idempotent so re-delivery is harmless."*
- *"The sweeper makes the DB — not the queue — authoritative: a lost job is recovered by re-scanning
  PENDING rows."*
- *"`processing_status = PENDING` + sweeper is a lightweight transactional outbox; the full version
  is a separate outbox table + relay."*
- *"RQ can't enqueue functions from `__main__` — scheduled jobs must have a stable import path."*

---

## 10. Self-test
1. What are the four failure modes, and which layer defends each?
2. Why is Postgres (not Redis) the source of truth here?
3. How does the sweeper recover a job that was completely lost from Redis?
4. Why must the sweeper's scheduled function live outside the `__main__` module?
5. RQ-scheduled job vs standalone loop — one tradeoff each.
6. What does Redis AOF `everysec` guarantee, and what covers the residual window?
7. How is `processing_status = PENDING` + sweeper related to the transactional outbox?
8. Why is idempotency a prerequisite for all of this to be safe?
