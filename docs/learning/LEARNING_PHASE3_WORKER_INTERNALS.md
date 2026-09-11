# Learning: Phase 3 Worker Internals (the actual code)

> Companion to `LEARNING_PHASE3_ASYNC.md` (which covers the *concepts*: queues, brokers, Celery vs
> RQ). This doc walks the *implementation* we built — enqueue-after-commit, the job function,
> idempotency, the pipeline, and how the worker process runs. Keyed to `app/worker/`,
> `app/adapters/queue/`, and `app/services/ticket_service.py`.

---

## 1. The end-to-end path (create → process)

```
POST /api/v1/tickets
  │
  ▼ TicketService.create_ticket()
  │   with session_scope():                # transaction 1
  │     INSERT ticket (processing_status=PENDING)
  │     INSERT CREATED event
  │   COMMIT ───────────────────────────┐
  │                                      │  (only now is the ticket durably saved)
  │   self._queue.enqueue(               │
  │       process_ticket, str(id))  ─────┼──► Redis  (RQ pushes a job)
  ▼                                      │
201 response to client                   │
                                         ▼
                              WORKER PROCESS (separate container)
                                 rq worker polls Redis, pops the job
                                 │
                                 ▼ process_ticket(ticket_id)
                                    with session_scope():          # transaction 2
                                      load ticket
                                      pipeline: summary/spam/priority/route
                                      upsert ProcessingResult
                                      apply priority + department to ticket
                                      INSERT PROCESSED event
                                      set processing_status=DONE
                                    COMMIT
```

Two separate transactions in two separate processes, decoupled by Redis.

---

## 2. Enqueue AFTER commit — and why the order is critical

`app/services/ticket_service.py`:
```python
with session_scope() as session:
    ... create ticket + event ...
# ← transaction has COMMITTED here (scope exited)

try:
    self._queue.enqueue(process_ticket, str(ticket.id))
except Exception:
    logger.exception("failed to enqueue ...")   # do NOT fail the request
return ticket
```

Why enqueue is **outside** the `with` block (after commit):
- If you enqueued *inside* the transaction and the job started immediately, the worker could look up
  the ticket **before the transaction committed** → "ticket not found" race.
- Committing first guarantees the row is durably visible before any worker can pick it up.

Why enqueue failure is **swallowed** (try/except, no re-raise):
- The ticket is already created and committed — that succeeded. If Redis is momentarily down, we must
  not turn a successful creation into a 500.
- The ticket simply stays `processing_status = PENDING`. In Phase 4 a **sweeper** re-enqueues stuck
  PENDING tickets. So "enqueue failed" degrades to "processed a bit later", never "lost".

> This is a pragmatic version of the **transactional outbox** idea. The bulletproof version writes
> the job intent into the DB in the same transaction and a relay publishes it; here `processing_status
> = PENDING` *is* the outbox marker, and the sweeper is the relay. (Phase 4.)

---

## 3. The job function — `process_ticket(ticket_id: str)`

`app/worker/tasks.py`. Key design points:

### a) Argument is a `str`, not a `UUID`
```python
def process_ticket(ticket_id: str) -> None:
    tid = UUID(ticket_id)
```
RQ **serializes job arguments** (default: pickle) to store them in Redis. We pass `str(ticket.id)`
and re-parse inside — passing simple, stable types across the process boundary is safer and clearer
than relying on serialization of richer objects. **Never pass ORM objects or DB sessions** to a job;
pass an id and re-load inside the worker.

### b) The worker initialises its own DB engine
```python
init_engine(get_settings())
```
The worker does **not** go through the FastAPI `lifespan`, so it must set up its own engine. `init_engine`
is idempotent, so calling it per-job is safe (defensive; the worker entrypoint also calls it once).

### c) Load fresh inside the worker's own transaction
```python
with session_scope() as session:
    ticket = session.get(Ticket, tid)
    if ticket is None:
        return            # nothing to do (e.g. deleted); don't crash
```
The worker re-loads the ticket in its **own** session/transaction — it shares no state with the API
process. This is the whole point of decoupling.

---

## 4. Idempotency — safe to run the same job twice

```python
if ticket.processing_status == ProcessingStatus.DONE:
    return                                  # guard: already processed

result = ticket.processing_result           # one-to-one
if result is None:
    result = ProcessingResult(ticket_id=ticket.id)   # create
    session.add(result)
result.summary = ...                         # else UPDATE the existing row (upsert)
```

Why it matters: queues are **at-least-once** — the same job can be delivered more than once (worker
crash after processing but before ack, retries, the Phase 4 sweeper). So the job must be safe to
re-run:
- **Guard** on `processing_status == DONE` → early return.
- **Upsert** the single `ProcessingResult` (create if missing, else update) → never duplicates.
- Keyed by `ticket_id` → the same input always converges to the same state.

Verified by `tests/test_processing_task.py::test_process_ticket_is_idempotent` (runs the job twice,
asserts exactly one `PROCESSED` event).

---

## 5. The pipeline — small pure functions (Strategy pattern)

`app/worker/pipeline/` — each step is a plain, dependency-free function so it's trivially testable
and swappable:

```python
summary            = DeterministicSummaryProvider().summarize(subject, description)
is_spam            = detect_spam(subject, description)            # spam.py
suggested_priority = assign_priority(subject, description, is_spam)  # prioritize.py
routed_department  = route_department(ticket.category, is_spam)   # route.py
```

- **Deterministic simulation** (brief permits it): keyword heuristics, not ML.
- **Order matters:** spam is computed first because priority + routing depend on it (spam → LOW
  priority, → TRIAGE department).
- Each is behind a clean boundary — `SummaryProvider` is a **port** (swap in an LLM later); the
  others are pure functions that a real model/rules-engine could replace without touching the job.

### suggested vs applied (recap)
```python
# stored in processing_results (the record of what the worker decided):
result.summary, result.is_spam, result.suggested_priority, result.routed_department
# ALSO applied to the live ticket (the brief's "assign priority" / "route"):
ticket.priority   = suggested_priority
ticket.department = routed_department
ticket.processing_status = ProcessingStatus.DONE
```
`summary`/`is_spam` live only in the result; priority/department are applied to the ticket too.

---

## 6. Failure handling

```python
try:
    ... pipeline + persist ...
except Exception as exc:
    ticket.processing_status = ProcessingStatus.FAILED
    session.add(TicketEvent(event_type=PROCESSING_FAILED, note={"error": str(exc)}))
    raise                                   # re-raise so RQ marks the job failed
```
- We record the failure **in the DB** (`FAILED` status + `PROCESSING_FAILED` event with the error)
  so it's inspectable.
- We **re-raise** so RQ moves the job to its failed registry (and can retry — Phase 4). Swallowing it
  would hide the failure from the queue.
- The `session_scope` still commits the FAILED status (the status write is what we want to persist).

---

## 7. The RQ adapter (producer side)

`app/adapters/queue/rq_task_queue.py`:
```python
class RQTaskQueue:
    def __init__(self, redis_url, queue_name="tickets"):
        self._connection = Redis.from_url(redis_url)   # lazy — no connection yet
        self._queue = Queue(queue_name, connection=self._connection)

    def enqueue(self, func, *args, **kwargs) -> str:
        job = self._queue.enqueue(func, *args, **kwargs)
        return str(job.id)
```
- Implements the `TaskQueue` **port** → the service depends on the interface, not RQ.
- `Redis.from_url` is lazy (connects on first use), which is why building the container in tests
  doesn't require a live Redis.
- `enqueue(func, *args)` stores a reference to the function + serialized args in Redis. The **worker**
  must be able to import that same `func` path (`app.worker.tasks.process_ticket`) — which it can,
  because it runs the same codebase/image.

---

## 8. The worker process (consumer side)

`app/worker/worker.py`, run as `python -m app.worker.worker`:
```python
configure_logging(settings.log_level)
init_engine(settings)                        # worker sets up its own DB engine
connection = Redis.from_url(settings.redis_url)
queue = Queue(settings.queue_name, connection=connection)
Worker([queue], connection=connection).work(with_scheduler=True)
```
- `worker.work()` is a **blocking loop**: poll Redis → pop a job → import & call the function →
  mark done/failed → repeat.
- It's a **separate container** from the API (same image, different `command`), so it scales and
  fails independently. The observed logs:
  ```
  worker starting {queue: tickets, redis: ...}
  Worker ...: tickets: app.worker.tasks.process_ticket('845a...')
  process_ticket: done {is_spam: false, priority: HIGH, department: ENGINEERING}
  Successfully completed ... in 0.066s
  ```

---

## 9. Why the same Docker image runs API and worker

`docker-compose.yml`:
```yaml
api:    { build: . ,           ... }                  # uvicorn (default CMD)
worker: { image: ticket-master-api,
          command: ["python","-m","app.worker.worker"] }   # same image, different command
```
One image contains the whole codebase; the **command** decides the role. Benefits: build once, no
code duplication, guaranteed identical dependencies/models between producer and consumer. (This also
sidestepped the flaky-network rebuild — only one image to build.)

---

## 10. Testing async without Redis (the ports payoff)

- **Pipeline steps** — pure functions → unit-tested directly (`tests/test_pipeline.py`).
- **The job** — call `process_ticket(id)` **directly** in a test against the test DB; no Redis needed
  (`tests/test_processing_task.py`). This is why the job is a plain function keyed by id.
- **Enqueue behaviour** — inject a `FakeTaskQueue` (records calls) via the container in `conftest.py`,
  so API tests assert "a job was enqueued" without a broker. Swapping the real adapter for a fake is
  exactly what the `TaskQueue` port enables.

---

## 11. Interview soundbites

- *"Enqueue after commit, never inside the transaction — otherwise the worker can race ahead of the
  commit and not find the row."*
- *"Jobs take an id, not an object — you re-load inside the worker's own session. Never pass ORM
  objects or sessions across the process boundary."*
- *"Queues are at-least-once, so the job is idempotent: a DONE guard + upsert of the single result
  row means re-delivery is harmless."*
- *"Enqueue failure doesn't fail creation; the ticket stays PENDING and a sweeper retries — a
  pragmatic outbox."*
- *"API and worker are the same image, different command — build once, identical deps, independent
  scaling."*

---

## 12. Self-test
1. Why is `enqueue` called after the `with session_scope()` block, not inside it?
2. Why does enqueue failure not fail the request, and what recovers the ticket?
3. Why does `process_ticket` take a `str` id and re-load the ticket instead of receiving the object?
4. Two mechanisms that make the job idempotent?
5. Why is spam computed before priority and routing?
6. Why re-raise in the failure handler instead of swallowing?
7. How do the tests exercise the job without a running Redis?
8. Why can the same Docker image serve as both API and worker?
