# Learning notes (deep-dives)

Optional reference material written alongside the build to explain the *why* behind each decision.
These are **not required** to run or review the service — the runnable system and its design are
covered by the top-level `README.md` and `docs/ARCHITECTURE.md`.

| Doc | Topic |
|-----|-------|
| `LEARNING_PHASE0.md` | Build order, project structure, pyproject/lockfile, env parity, `uv` |
| `LEARNING_CONFIG_12FACTOR.md` | 12-factor config, `Settings`, precedence, secret management |
| `LEARNING_PORTS_AND_ADAPTERS.md` | Hexagonal architecture, ports/adapters/container, naming |
| `LEARNING_SQLALCHEMY.md` | SQLAlchemy 2.0 models: `Mapped`, `mapped_column`, relationships |
| `LEARNING_PHASE1.md` | ORM vs Alembic, Django vs FastAPI, table modeling, native enums |
| `LEARNING_MIGRATIONS_IN_PRODUCTION.md` | Migration lifecycle, reproducibility, safe schema changes, expand/contract |
| `LEARNING_REQUEST_LIFECYCLE.md` | Full low-level trace of a request through every layer |
| `LEARNING_PHASE3_ASYNC.md` | Queues/brokers/workers; Redis/RabbitMQ/Kafka/SQS; Celery vs RQ |
| `LEARNING_PHASE3_WORKER_INTERNALS.md` | Enqueue-after-commit, the job, idempotency, the pipeline |
| `LEARNING_PHASE4_RELIABILITY.md` | At-least-once, retries, the sweeper, Redis AOF, the outbox |
| `LEARNING_PHASE5.md` | Polish, deliverables, and what makes a submission read as senior |
