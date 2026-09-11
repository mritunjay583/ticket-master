# Phase 1 — Deep Dive (Learning Notes)

> Study companion for Phase 1 (data model & migrations). Covers the tools, the "why", and the data
> modeling concepts. Grows as we build the phase.

---

## 1. SQLAlchemy vs Alembic — what each is for

They are two separate tools (by the same author, Mike Bayer) that pair up.

### SQLAlchemy = the ORM (talks to the DB at runtime)
An **ORM (Object-Relational Mapper)** lets you work with rows as Python objects instead of raw SQL.

```python
# instead of: INSERT INTO tickets (subject, status) VALUES ('Login broken', 'OPEN')
ticket = Ticket(subject="Login broken", status=TicketStatus.OPEN)
session.add(ticket)
session.commit()

# instead of: SELECT * FROM tickets WHERE id = 5
ticket = session.get(Ticket, 5)
```

Handles: connections, object↔row mapping, query building, transactions. Used **on every request**.

### Alembic = the migration tool (evolves the DB *shape* over time)
Your `Ticket` **model** is Python; the actual **table** in Postgres is a separate thing that must be
created and evolved. Adding a column to the model does NOT change the real table — you need a
**migration**. Alembic generates + applies those as versioned scripts:

```
alembic/versions/
  001_create_tickets_table.py     # create tickets table
  002_add_department_column.py    # add a column
  003_add_index_on_status.py      # add an index
```

`alembic upgrade head` runs them in order to bring ANY database (teammate's, CI, prod) to the current
schema; `alembic downgrade` reverses them.

### Division of labor
| | SQLAlchemy | Alembic |
|---|-----------|---------|
| Job | read/write **data** (rows) | change the **schema** (tables/columns/indexes) |
| When | runtime, every request | deploy time / when schema changes |
| Analogy | *using* the building | *renovating* the building |
| Answers | "give me ticket #5" | "make the DB have a `department` column" |

Alembic reads your SQLAlchemy models to auto-generate migrations. **SQLAlchemy = data; Alembic =
structure.**

> Why two tools, not one? Migrations are dangerous, ordered, reviewable operations on production
> data. You want them as explicit versioned files you can inspect and roll back — not something that
> silently happens at app boot.

---

## 2. Why Django has its own ORM but FastAPI doesn't (framework philosophy)

### Django = "batteries included" (full framework)
Gives you everything, tightly integrated: its own ORM (`django.db.models`), its own migrations
(`makemigrations`/`migrate`), admin panel, auth, templating, forms. One opinionated cohesive stack —
you use "the Django way." The ORM is built in because Django's goal is a complete web stack.

### FastAPI = microframework (do one thing well, compose the rest)
FastAPI focuses on the **API layer** — routing, request/response validation (Pydantic), async,
OpenAPI docs — and leaves everything else to you. **No built-in ORM, migrations, admin, or auth.**
You plug in the best tool per concern: SQLAlchemy + Alembic (our choice), or SQLModel, Tortoise,
Peewee, raw SQL, etc.

### The tradeoff
| | Django (integrated) | FastAPI (composable) |
|---|---------------------|----------------------|
| Setup speed | fast — all included | slower — assemble pieces |
| Flexibility | lower ("the Django way") | higher — swap any layer |
| Learning curve | one big framework | several focused tools |
| Coupling | ORM tied to framework | ORM independent/reusable |
| Best for | full web apps, admin-heavy CRUD | APIs, microservices, custom architectures |

Neither is "better" — different bets. Django optimizes for cohesion + speed; FastAPI for flexibility
+ separation of concerns.

### Why FastAPI's choice helps OUR architecture
Because FastAPI doesn't force an ORM, our business logic isn't coupled to a framework's data layer.
SQLAlchemy sits **behind our `TicketRepository` port** as a swappable adapter. In Django the ORM is
woven through the framework, so this clean hexagonal separation is harder. FastAPI's "no built-in
ORM" is precisely what lets us keep the DB behind a swappable port.

```
Django:   [ Router + ORM + Migrations + Admin + Auth ]     one integrated framework

FastAPI:  [ Router + validation + docs ]  focused API layer
             + SQLAlchemy  (ORM — our choice)
             + Alembic     (migrations — our choice)
             + ... other tools we plug in
```

**One-liner:** *SQLAlchemy is the ORM (data at runtime); Alembic is its migration companion (schema
over time). Django bundles its own ORM as a batteries-included framework; FastAPI is a focused
microframework that leaves data-layer choices to you — which is exactly what lets us keep the DB
behind a swappable port.*

---

## 3. The four tables and why `ProcessingResult` is separate

Phase 1 creates four tables, each with a distinct concern:

```
        ┌─────────────┐
        │   tickets    │  the live entity (customer data + current status/priority/department)
        └──────┬───────┘
               │ 1
        ┌──────┴───────────────┬────────────────────────┐
        │ many                 │ 1  (one-to-one)         │
        ▼                      ▼                          
┌────────────────┐   ┌──────────────────────┐   ┌──────────────┐
│ ticket_events   │   │ processing_results    │   │   agents      │  (referenced by tickets.
│ append-only     │   │ async worker output   │   │  assignee)    │   assigned_agent_id)
│ audit history   │   │ (one row per ticket)  │   └──────────────┘
└────────────────┘   └──────────────────────┘
```

- **`tickets`** — current, mutable state (agents change status/priority/department).
- **`ticket_events`** — append-only log of *every* change (many rows/ticket; never edited).
- **`processing_results`** — the *output of the background job* (one row/ticket).
- **`agents`** — optional users/agents (for assignment + routing).

### Why not put processing output on the ticket?
| Reason | Explanation |
|--------|-------------|
| Different origin | Ticket = what the *customer* submitted. Result = what the *system computed*. |
| Different lifecycle | Ticket exists instantly; the result appears later (worker), may be re-run. |
| Clean nullability | "not processed yet" = **no row exists**, instead of a pile of nullable columns on the ticket. |
| Enforced 1:1 | `processing_results.ticket_id` is a FK with `UNIQUE` → exactly one result per ticket, guaranteed by the DB. |
| No bloat | Every ticket read would otherwise drag along `summary`, `is_spam`, … even when unused. |

### The "suggested vs applied" rule (what goes where)
The brief says only "the processing result should be stored in the database" — it does not say to
mutate the ticket. We use a **hybrid** that matches the brief's verbs:

| Field | In `processing_results` | Also applied to `ticket` | Rationale |
|-------|-------------------------|--------------------------|-----------|
| `summary` | ✅ | ❌ | computed artifact, not a ticket attribute |
| `is_spam` | ✅ | ❌ | a verdict, not core ticket data |
| `suggested_priority` | ✅ | ✅ `ticket.priority` | brief: "assign ticket priority" (a ticket action) |
| `routed_department` | ✅ | ✅ `ticket.department` | brief: "route to the correct department" (a ticket action) |

So `processing_results` is the **immutable record of what the worker decided**; the ticket reflects
the **applied, overridable** values. This lets you audit automated decisions and measure agent
overrides — a senior-level modeling insight, and a faithful reading of the requirements.

---

## 4. Does Alembic create extra tables like Django?

**Django** auto-creates several tables you didn't define: `django_migrations` (tracks applied
migrations) plus feature tables from built-in apps — `auth_user`, `django_session`,
`django_admin_log`, `django_content_type`, … (batteries-included).

**Alembic** creates exactly **one** tiny bookkeeping table:

```
alembic_version
────────────────
version_num      → e.g. 'a1b2c3d4e5f6'  (one row: the current migration revision)
```

Its only job: remember which migration the DB is currently at, so `alembic upgrade` knows what still
needs to run. **No auth/admin/session tables** — because FastAPI/SQLAlchemy don't bundle those. Every
other table in the DB is one *you* defined (`tickets`, `ticket_events`, `processing_results`,
`agents`). Nothing hidden — consistent with the "you choose everything" philosophy.

| | Django migrations | Alembic |
|---|-------------------|---------|
| Bookkeeping table | `django_migrations` | `alembic_version` |
| Extra feature tables | many (auth/admin/session/…) | none |
| Philosophy | brings its own tables | only what you define + one version tracker |

---

## 5. Native PostgreSQL enums + the Alembic roundtrip gotcha (real bug we hit)

We use **native PG enum types** (`native_enum=True`) because the brief asks for "enum usage where
appropriate" and it enforces valid values *at the database level* (not just in Python).

### Two problems native enums cause with Alembic — and the fixes

**Problem 1: the same enum used by multiple tables.**
`department` is referenced by both `agents` and `tickets`; `ticket_priority` by `tickets` and
`processing_results`. If each model created its own `SAEnum(...)`, SQLAlchemy could emit
`CREATE TYPE department` twice → error.
**Fix:** define each enum type **once** in `app/models/enum_types.py` and reuse the same object
across models. SQLAlchemy then creates it a single time.

**Problem 2 (the big one): downgrade doesn't drop enum types.**
Autogenerate creates enum types implicitly on first column use, but `drop_table` on downgrade does
**NOT** drop the enum type (a PG enum is a standalone object, independent of tables). So:
```
upgrade   → CREATE TYPE department; CREATE TABLE ...        ✅
downgrade → DROP TABLE ...        (enum 'department' stays)  ⚠️
upgrade   → CREATE TYPE department  → ERROR: type already exists  ❌
```
We hit exactly this: `psycopg.errors.DuplicateObject: type "department" already exists`.

**Fix — manage enums explicitly in the migration:**
1. Define the enums with `postgresql.ENUM(..., create_type=False)` so column creation does **not**
   auto-emit `CREATE TYPE`.
2. In `upgrade()`: create them once up front — `enum.create(bind, checkfirst=True)`.
3. In `downgrade()`: drop them explicitly at the end — `enum.drop(bind, checkfirst=True)`.

Now the upgrade→downgrade→upgrade roundtrip works cleanly. **This is a classic senior-level
migration detail** — knowing that PG enum types outlive their tables and must be dropped by hand.

### Verified
`alembic upgrade head` → `downgrade base` → `upgrade head` all succeed; the DB ends with 4 tables +
`alembic_version` and 6 enum types.

---

## 6. Indexes — what we added and why

Indexes speed up reads at the cost of slightly slower writes + extra storage. We index exactly the
columns the API filters/sorts on (from the brief's List requirement):

| Index | Columns | Why |
|-------|---------|-----|
| `ix_tickets_status` | status | filter by status |
| `ix_tickets_priority` | priority | filter by priority |
| `ix_tickets_category` | category | filter by category |
| `ix_tickets_created_at` | created_at | default ordering / pagination |
| `ix_tickets_status_priority` | (status, priority) | common combined filter (composite) |
| `ix_tickets_processing_status` | processing_status | the async sweeper's lookup (Phase 4) |
| `ix_ticket_events_ticket_id_created_at` | (ticket_id, created_at) | fast per-ticket timeline reads |
| `ix_agents_email` (unique) | email | uniqueness + lookup by email |

Rule of thumb: **index the columns you filter, join, or sort by** — not every column (each index
adds write cost). We don't index `subject`/`description` (free-text; would need full-text search, out
of scope).

---

## 7. Key modeling choices recap

- **UUID primary keys** (not auto-increment ints): safe to expose publicly (no enumeration of
  "ticket 1, 2, 3…"), and generatable without a DB round-trip.
- **DB-managed timestamps** (`server_default=now()`, `onupdate=now()`): correct even under concurrent
  writers; not set in Python.
- **`ondelete` policies:** `tickets.assigned_agent_id → SET NULL` (deleting an agent unassigns their
  tickets, doesn't delete them); `ticket_events`/`processing_results → CASCADE` (children die with the
  ticket).
- **`processing_status` on the ticket** doubles as a lightweight outbox marker for the async work
  (Phase 3/4).
