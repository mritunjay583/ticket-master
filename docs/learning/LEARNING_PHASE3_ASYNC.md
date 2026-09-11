# Learning: Async Processing — Queues, Brokers & Workers (Phase 3)

> What a queue is, the producer/broker/consumer model, and — crucially — the fact that async
> processing is **TWO separate choices**: the *broker* (buffer) and the *worker framework* (runs the
> jobs). Covers Redis/RabbitMQ/Kafka/SQS, Celery vs RQ, and which to pick for what.

---

## 1. What is a queue?

A **queue** holds messages in the middle so a **producer** can hand off work and a **consumer**
picks it up later, independently.

```
PRODUCER ──put(job)──►  [ QUEUE ]  ──get(job)──►  CONSUMER
(API server)          (broker)                   (worker)
```

Properties: **asynchronous** (producer doesn't wait), **decoupled** (they only know the queue),
**buffered** (jobs wait if the consumer is down — not lost), **load-leveling** (a burst is drained at
the worker's pace).

### The worker is a SEPARATE PROCESS, not scheduled by the API
```
┌────────────────┐      ┌────────┐      ┌────────────────────┐
│ FastAPI (uvicorn)│──push─►│ Redis  │◄─poll─│ Worker (RQ process) │
│ create_ticket()  │      │ broker │      │ process_ticket()     │
│ returns 201 fast │      │        │      │ writes to Postgres   │
└────────────────┘      └────────┘      └────────────────────┘
   Container 1            Container 2       Container 3 (same image,
   command: uvicorn                          command: rq worker)
```
The API does **not** run/schedule the worker — it just drops a job in the broker and returns. The
worker independently polls and processes. Same codebase (models/config/DB reused), **independent
processes**.

Why separate: API stays fast (returns before processing), independent scaling (N workers, M APIs),
failure isolation (a dead worker doesn't break the API; jobs wait in the broker).

> NOT the same as FastAPI `BackgroundTasks`, which run *inside the API process* — no separate
> process, no durability, lost on restart, no independent scaling. We use a real queue + worker.

### Maps 1:1 onto the Kafka production model
| Concept | Production (narad) | Ours |
|---------|--------------------|------|
| Producer | narad-server API | FastAPI `create_ticket` |
| Broker (in-between) | Kafka | Redis |
| Consumer/worker | `narad-*-consumer` (separate Go app) | RQ worker (separate process) |
| Message | Kafka event | RQ job (`process_ticket`, ticket_id) |
| Result store | DynamoDB/ES | Postgres `processing_results` |
Same shape (produce → broker → separate consumer → persist); different broker scale.

---

## 2. The BIG idea: async = TWO independent choices

```
                 ┌──────────────┐        ┌────────────────┐
 PRODUCER ──────►│ 1. BROKER     │◄───────│ 2. WORKER       │
 (your API)      │ (the buffer)  │        │ FRAMEWORK       │
                 └──────────────┘        │ (runs the jobs) │
                                         └────────────────┘
   what STORES messages?                  what EXECUTES them?
   Redis / RabbitMQ / Kafka / SQS         Celery / RQ / Dramatiq / custom
```

These are **orthogonal**. Common confusion: "Celery" is not a queue — it's a task *framework* that
uses a broker. "Kafka" is not a worker — it's a broker you write a consumer for. You pick **one from
each column**.

---

## 3. Choice #1 — the Broker (buffer in the middle)

| Broker | Type | Ops burden | Pros | Cons | Best for |
|--------|------|-----------|------|------|----------|
| **Redis** | in-memory store | low | simple, fast, one container, often already present | in-memory (durability via AOF), basic routing | background jobs, caching, simple/medium queues **(our choice)** |
| **RabbitMQ** | message broker (AMQP) | medium | rich routing (exchanges/topics/priority), reliable acks, built-in DLQ | another server to operate; more concepts | complex routing, guaranteed delivery, enterprise messaging |
| **Kafka** | event-streaming log | high | huge throughput, durable **replayable** log, multi-consumer **fan-out**, event sourcing | heavy to operate; job model built on top | high-volume streams, many consumers on one event **(narad)** |
| **AWS SQS** | managed queue | ~zero | no servers, auto-scale, durable, built-in DLQ | AWS lock-in; needs cloud creds; no rich routing | production on AWS, no-ops |

---

## 4. Choice #2 — the Worker/Task framework (runs the jobs) — Celery vs RQ

### Celery — heavyweight, feature-rich
- Brokers: RabbitMQ **or** Redis.
- Features: scheduled/periodic tasks (**beat**), retries, **workflows** (chains/groups/chords), rate
  limiting, result backends, priorities, multi-queue routing.
- Cons: complex config, steep learning curve, heavier to operate.
- Best for: complex production workloads — scheduled jobs, multi-step pipelines, fine control.

### RQ (Redis Queue) — lightweight, simple  ← our choice
- Broker: **Redis only**.
- Features: enqueue a function, run a worker, basic retries, failed-job registry, scheduling via
  rq-scheduler. Minimal, readable.
- Cons: Redis-only; fewer advanced features (no rich workflows, weaker routing).
- Best for: simple/medium background jobs where simplicity wins.

### Others
- **Dramatiq** — modern middle ground (simpler than Celery, sturdier than RQ; Redis/RabbitMQ).
- **Arq** — asyncio-native task queue on Redis; pairs well with async FastAPI.
- **Custom consumer** — with Kafka/SQS you often write your own loop (narad does this in Go).

### Celery vs RQ — direct comparison
| | Celery | RQ |
|---|--------|----|
| Complexity | high | low |
| Brokers | RabbitMQ or Redis | Redis only |
| Scheduled/periodic | ✅ beat | ⚠️ rq-scheduler |
| Workflows (chain/group/chord) | ✅ rich | ❌ minimal |
| Retries/routing/priorities | ✅ extensive | ⚠️ basic |
| Learning curve | steep | gentle |
| Best when | complex/high-scale/scheduled/multi-step | simple jobs, fast setup |

> One-liner: *Celery = powerful but complex; RQ = simple and readable. Both are worker frameworks on
> top of a broker (Celery: RabbitMQ/Redis; RQ: Redis).*

---

## 5. You combine one from each column

```
RQ            + Redis        ← ours (simple job + simple broker)
Celery        + Redis        ← common, more features, still simple broker
Celery        + RabbitMQ     ← classic enterprise Python
custom worker + Kafka        ← high-scale streaming / fan-out (narad)
Lambda/custom + SQS          ← managed, no-ops, AWS-native
Dramatiq/Arq  + Redis        ← modern alternatives
```

---

## 6. Which for OUR use case, and why

Workload: "on ticket creation, run **one** enrichment job, store the result."
- One job type → no need for Celery's workflow/routing machinery.
- Modest volume → no need for Kafka's throughput/replay.
- One-command local run → Redis (one container) beats RabbitMQ/Kafka (multi-container) or SQS (cloud
  creds).
- The brief explicitly lists **"Redis + RQ"**.

→ **Broker: Redis. Framework: RQ.** And because it's behind our `TaskQueue` **port**, swapping to
SQS or Celery later = a new adapter + one container line, no service changes.

### When you'd choose differently (interview table)
| Use case | Broker | Framework |
|----------|--------|-----------|
| Simple background jobs (ours) | Redis | RQ |
| Scheduled + multi-step workflows | Redis/RabbitMQ | Celery |
| Complex routing / guaranteed delivery | RabbitMQ | Celery |
| High-volume events, fan-out, replay | Kafka | custom consumer |
| Managed / no-ops on AWS | SQS | Lambda / Celery |
| Async-native FastAPI, simple jobs | Redis | Arq |

---

## 7. Interview soundbites

- *"Async processing is two orthogonal choices: the broker (Redis/RabbitMQ/Kafka/SQS) and the worker
  framework (Celery/RQ/Dramatiq/custom). Celery isn't a queue; Kafka isn't a worker."*
- *"The worker is a separate process, not the API scheduling itself — that's what gives fast
  responses, independent scaling, and failure isolation. FastAPI BackgroundTasks don't give you
  that."*
- *"I chose Redis+RQ: one job type, modest volume, one-command-local. Behind a TaskQueue port, so
  SQS/Celery is a drop-in later."*
- *"Kafka shines for high-throughput, replayable, multi-consumer fan-out — which is why the reference
  production system uses it; our single-job case doesn't need that weight."*

---

## 8. Self-test
1. What two independent choices make up an async processing setup?
2. Is Celery a queue? Is Kafka a worker? Explain.
3. Why is the worker a separate process instead of FastAPI scheduling it?
4. Celery vs RQ — three concrete differences.
5. Redis vs Kafka as a broker — when each?
6. Why Redis+RQ for this project, and how would you swap to SQS later?
7. How does this map onto the Kafka producer→broker→consumer production model?
