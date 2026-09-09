# Learning: Ports, Adapters & the Container (Hexagonal Architecture)

> A standalone deep-dive on the architectural backbone of this project — why business logic depends
> on *interfaces* (ports), why concrete tech is wired in one place (the container), and how to decide
> what deserves to be a port. This is the concept behind `app/core/ports/` and `app/core/container.py`.

---

## 1. The problem it solves

Business logic needs to touch the outside world: save a ticket, enqueue a job, generate a summary.
The naive approach calls tools directly:

```python
# WRONG — business logic welded to specific tech
import sqlalchemy, redis
def create_ticket(...):
    session.add(ticket)        # tied to SQLAlchemy
    redis.rpush("jobs", ...)   # tied to Redis
```

Consequences:
- Can't test without a real Postgres + Redis.
- Can't swap Postgres → MongoDB without rewriting services.
- Business rules are tangled with I/O plumbing.

---

## 2. The three concepts

### Port = an interface (the "what")
A contract describing a capability by *what it does*, not *how*.

```python
class TicketRepository(Protocol):
    def create(self, session, ticket) -> Ticket: ...
    def get_by_id(self, session, ticket_id) -> Ticket | None: ...
```
Says "tickets can be created/fetched." Says nothing about SQL, Postgres, or tables.

### Adapter = a concrete implementation (the "how")
A class that fulfills a port using a specific technology.

```python
class SqlAlchemyTicketRepository:   # satisfies TicketRepository
    def create(self, session, ticket): ...   # uses SQLAlchemy
```
You could also write `MongoTicketRepository` or `InMemoryTicketRepository`. All satisfy the *same*
port; the business logic can't tell them apart.

### Container = the composition root (the "which")
The single place that picks concrete adapters and hands them to services.

```python
# container.py — the ONLY place that knows concrete classes
def build_container(settings):
    ticket_repo = SqlAlchemyTicketRepository()
    queue = RQTaskQueue(settings.redis_url)
    return Container(ticket_repo=ticket_repo, queue=queue)
```
Services receive these via dependency injection (FastAPI `Depends`) — never construct them inline.

---

## 3. Why it's standard: Dependency Inversion (the "D" in SOLID)

Without ports, dependency flows from high-level to low-level:
```
Service ──depends on──► SQLAlchemy      (policy tied to detail)
```

With a port, you invert it — both sides depend on the abstraction in the middle:
```
Service ──► TicketRepository (port) ◄── SqlAlchemyRepo
(high-level)     (abstraction)          (low-level detail)
```

The high-level policy (business rules) no longer depends on low-level detail (which DB). This is the
**Dependency Inversion Principle**, and it's the cleanest known way to keep business logic
independent of infrastructure — which is why it's an industry standard (Hexagonal Architecture /
Ports & Adapters, a.k.a. Clean/Onion Architecture).

---

## 4. Pros

| Benefit | Why |
|---------|-----|
| **Swappability** | Change DB/queue/provider = new adapter + one container line. Services untouched. |
| **Testability** | Inject a fake/in-memory adapter in tests — no real DB/Redis. Tests run in ms. |
| **Separation of concerns** | Business rules in services; plumbing in adapters. Each stays simple. |
| **Parallel work** | Build a service against the port while someone else builds the adapter. |
| **Delayed decisions** | Code the whole domain before committing to exact tech. |
| **Documented boundary** | The port *is* the contract between layers. |

## 5. Cons (be honest)

- **More indirection** — extra interface files; overkill for a tiny script.
- **Boilerplate** — you write the interface *and* the implementation.
- **Over-application risk** — not everything needs a port (see §6).

Worth it when the thing is an **external dependency** or **likely to change**. Not worth it for pure
in-process logic.

---

## 6. What SHOULD be a port? (the heuristic)

Ask: **"Is this talking to the outside world, or could it reasonably be implemented more than one
way?"** If yes → port.

**Good port candidates** (edge of the app: I/O, external services, swappable strategies):
- `TicketRepository` — storage (Postgres today, could be anything)
- `TaskQueue` — background jobs (Redis/RQ today, could be SQS/Kafka)
- `SummaryProvider` — swappable strategy (rule-based today, LLM later)
- `EmailSender` — external service (SMTP / SES / SendGrid)
- `FileStorage` — local disk vs S3 vs GCS
- `Clock` (`now()`) — trivial-looking, but a port lets tests freeze time
- `PaymentGateway`, `Notifier`, `SearchIndex`, `Cache` — all external

**NOT ports** (plain in-process domain logic / data shapes):
- Pure functions & domain calculations — e.g. the status **state machine** (one sensible impl, no
  external dependency)
- DTOs / Pydantic schemas (data shapes, not behaviors)
- Simple value objects

Rule of thumb: **ports are for the edges (I/O, external systems, interchangeable strategies); the
core domain logic stays plain.**

---

## 7. Why a `Protocol` (not an abstract base class)?

This project uses `typing.Protocol` for ports:
```python
class TaskQueue(Protocol):
    def enqueue(self, func, *args, **kwargs) -> str: ...
```
- **Structural typing (duck typing):** an adapter satisfies the port just by having the right
  methods — no explicit `class X(TaskQueue)` inheritance needed. Looser coupling.
- **Great for test fakes:** a tiny fake class with the right methods "is a" TaskQueue automatically.
- `@runtime_checkable` allows `isinstance()` checks when needed.

(An `abc.ABC` is the alternative — stricter, requires explicit inheritance. Both are valid; Protocol
is lighter and favored for ports.)

---

## 8. The whole picture

```
        ┌──────────── application core ────────────┐
        │  services (business rules)                 │
        │     depend on ↓ (interfaces only)          │
        │  ports:  TicketRepository  TaskQueue ...   │
        └───────────────────▲────────────────────────┘
                            │ implemented by
       ┌────────────────────┼────────────────────┐
  SqlAlchemyRepo       RQTaskQueue        DeterministicSummary   ← adapters (edge)
       │                    │                     │
   Postgres              Redis              (rules / LLM)         ← real tech
                            ▲
                            │ wired by
                      container.py (composition root)
```

Everything points *inward* toward the abstractions. Tech sits on the outside, plugged in at one spot.

---

## 9. The acceptance test for the design

> "How do I switch from Postgres to MongoDB?"
> **Answer:** write `MongoTicketRepository` (satisfies the existing `TicketRepository` port), change
> one line in `container.py`. Services, routers, schemas, state machine, and tests: **untouched.**

If that's true, the architecture is doing its job.

---

## 10. Self-test

1. In one sentence each: what is a port, an adapter, and the container?
2. Which SOLID principle does this pattern embody, and what does it invert?
3. Why can tests run without a real database in this design?
4. Give three things that *should* be ports and two that should *not*.
5. Why is the status state machine **not** a port?
6. Why `Protocol` instead of an abstract base class here?
7. What exactly changes when you swap Redis/RQ for AWS SQS?

---

## 11. `Protocol` and `@runtime_checkable` — what they do at runtime

### Type hints are (mostly) ignored by the running interpreter
Python is dynamically typed. Hints like `x: int`, `-> str`, and `Protocol` are **not enforced by the
interpreter at runtime**. They exist for **mypy/Pyright, your IDE, and humans**.

```python
def add(a: int, b: int) -> int:
    return a + b
add("hello", "world")   # RUNS FINE → "helloworld". The int hints are not checked at runtime.
```
mypy would flag that; the interpreter shrugs.

So for a port like:
```python
@runtime_checkable
class SummaryProvider(Protocol):
    def summarize(self, subject: str, description: str) -> str: ...
```
the value of the `Protocol` + hints to the *running program* is essentially **zero** — it's a
development-time safety net (static checking + autocomplete).

### `Protocol` = structural typing ("checked duck typing")
A class satisfies a `Protocol` if it has the right methods — **no inheritance required**.

```python
class DeterministicSummary:               # does NOT inherit SummaryProvider
    def summarize(self, subject, description): ...
provider: SummaryProvider = DeterministicSummary()   # ✅ mypy happy (shape matches)
```

Contrast with `abc.ABC` (nominal typing) which requires explicit `class X(Port)` inheritance.

| | `Protocol` (structural) | `ABC` (nominal) |
|---|---|---|
| Must inherit the interface? | No — match methods | Yes |
| Coupling | Looser (adapter needn't import the port) | Tighter |
| Test fakes | Any matching class works | Must inherit |

Why Protocol for ports: an adapter/test-fake satisfies the port **without importing or knowing about
it** → maximum decoupling.

### `@runtime_checkable` = the one bit that affects runtime
By default you **cannot** do `isinstance(obj, SomeProtocol)` — it raises `TypeError`.
`@runtime_checkable` enables it:
```python
isinstance(DeterministicSummary(), SummaryProvider)   # ✅ works ONLY with the decorator
```
**Limitation:** it only checks that method **names exist**, not their signatures/types. Real
signature checking is mypy's job (static). So runtime checking is shallow; the decorator is a
convenience for optional runtime guards. We add it defensively; if we never call `isinstance`, it's
harmless and inert.

### Libraries that DO read hints at runtime (different from the language enforcing them)
Some libraries deliberately inspect annotations while running — and act on them:
- **Pydantic** (`Settings`, models) reads field types to **validate + coerce** data at runtime.
- **FastAPI** reads route hints to parse/validate requests and build OpenAPI docs.

This is opt-in behavior *by the library*, not the interpreter enforcing types. Same-looking hint,
totally different runtime consequence.

**Mental model:**
```
Type hints / Protocol         → for mypy + IDE + humans; interpreter ignores at runtime.
@runtime_checkable            → the ONE part that adds runtime power (enables isinstance; name-only).
Pydantic/FastAPI field types  → libraries CHOOSE to read hints at runtime and enforce/validate.
```

---

## 12. The container is ONE (composition root), not one-per-port

A frequent misconception: "is there a container per port (a `TaskQueueContainer`, a
`TicketRepoContainer`, …)?" **No. There is exactly one container for the whole app.**

The container is the **composition root** — the single place the entire object graph is assembled.
It holds *all* wired dependencies together:

```python
@dataclass(frozen=True)
class Container:
    settings: Settings
    ticket_repo: TicketRepository        # (added in later phases)
    event_repo: TicketEventRepository
    task_queue: TaskQueue
    summary_provider: SummaryProvider

def build_container(settings: Settings) -> Container:
    # ONE place that knows every concrete choice:
    ticket_repo = SqlAlchemyTicketRepository()
    event_repo  = SqlAlchemyEventRepository()
    task_queue  = RQTaskQueue(settings.redis_url)
    summary     = DeterministicSummaryProvider()
    return Container(settings, ticket_repo, event_repo, task_queue, summary)
```

### Why one, not per-port
The whole point is a **single place that knows all the concrete wiring**. Splitting it per port would
re-scatter exactly the knowledge you centralized. Swapping Redis→SQS is then a one-line change *here*,
not a codebase hunt.

**Analogy:**
- Ports = the *spec* of parts a car needs (an engine, wheels, a battery).
- Adapters = the *actual* parts.
- Container = the **one assembly line** that builds the whole car from those parts.
You don't build a separate assembly line per part.

### The counts that resolve the confusion
| Concept | How many | Role |
|---------|----------|------|
| Port | many (one per capability) | *what* is needed |
| Adapter | many (≥1 per port) | *how* it's done |
| **Container** | **exactly one** | *assembles all adapters* and hands them out |

→ **many ports, many adapters, one container.**

### "Won't one container become a God object?"
In a large app it can grow. The fix is **organization inside the single root** — helper factories
(`build_repos()`, `build_queue()`) that the one `build_container()` calls. That's structure *within*
the composition root, not multiple containers. (DI frameworks like `dependency-injector` allow
"modules/sub-containers", but they still assemble into one root graph.)

**One-liner:** *Exactly one container — the composition root — wires every port's chosen adapter in a
single place; ports and adapters are many, the container is one.*

---

## 13. Naming conventions for ports (the suffix announces the role)

Port names are **not arbitrary** — they use established design-pattern vocabulary. The suffix tells
a reader what *kind* of boundary it is, without opening the file.

### "Repository" — what it means
A **Repository** (Martin Fowler / Domain-Driven Design) is:
> an object that acts like a **collection of domain entities**, hiding how they're actually stored.

Mental image: pretend all tickets live in an in-memory list; the repository is the object you ask to
add/find/update items. You call `ticket_repo.get_by_id(5)` and don't know or care whether it hits
Postgres, Mongo, or a dict. The word literally means *a place where things are stored* — that's its
job: the storage boundary for one entity type.

- `TicketRepository` → stores/retrieves `Ticket`s
- `TicketEventRepository` (file `event_repository.py`) → stores/retrieves `TicketEvent`s (audit rows)

Formula: **`<Entity>Repository`**, one per entity/aggregate. File = snake_case
(`event_repository.py`), class = PascalCase (`TicketEventRepository`).

### Common port suffixes and what they signal
| Suffix | Role / pattern | Example |
|--------|----------------|---------|
| `...Repository` | data storage/retrieval for an entity | `TicketRepository`, `TicketEventRepository` |
| `...Queue` | push work onto it for later processing | `TaskQueue` |
| `...Provider` | supplies/produces a value or capability | `SummaryProvider` |
| `...Service` | orchestrates business logic (a use-case) | `TicketService` |
| `...Gateway` / `...Client` | talks to an external system/API | `PaymentGateway`, `EmailClient` |
| `...Sender` / `...Notifier` | sends messages out | `EmailSender` |
| `...Factory` | creates other objects | `create_task_queue` |

So the ports in this project read as:
- `ticket_repository.py` → **Repository** (ticket storage)
- `event_repository.py` → **Repository** (audit-event storage)
- `task_queue.py` → **Queue** (push jobs)
- `summary_provider.py` → **Provider** (produce a summary)

### The golden rule: name the capability, not the technology
> Name a port after the **role/capability** it provides using standard pattern vocabulary — never
> after the tech behind it.

- ✅ `TicketRepository`, `TaskQueue`  — tech-agnostic
- ❌ `PostgresTicketStore`, `RedisQueue` — leaks the tech into the abstraction

The **tech name belongs on the adapter**, not the port:
```
Port (what):      TicketRepository            TaskQueue
Adapter (how):    SqlAlchemyTicketRepository   RQTaskQueue / SqsTaskQueue
```
Ports describe *what* is needed; adapter names reveal *how* it's done. If you ever see a technology
name in a port, that's a design smell — the abstraction is leaking.

**One-liner:** *"Repository" = the pattern for an object that stores/retrieves an entity while hiding
storage; port names use role suffixes (`Repository`/`Queue`/`Provider`/…) and stay tech-agnostic, with
the technology named only on the adapter.*
