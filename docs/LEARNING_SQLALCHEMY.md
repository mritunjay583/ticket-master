# Learning: SQLAlchemy 2.0 ORM (keyed to our models)

> A guided tour of SQLAlchemy 2.0 using this project's actual models (`app/models/`). Covers the
> declarative base, `Mapped`/`mapped_column`, defaults, mixins, foreign keys, relationships, and
> table args. Read alongside `app/models/ticket.py` and `app/models/agent.py`.

---

## 0. The big picture

An ORM maps: **class → table**, **instance → row**, **attribute → column**. SQLAlchemy translates
between Python objects and SQL. Version 2.0 (what we use) does this with **typed** declarations —
your Python type hints drive the mapping, which is why strict mypy works.

---

## 1. `DeclarativeBase` — the root of all models

```python
class Base(DeclarativeBase):
    ...
```
Every model inherits from `Base`. It provides:
- a shared **registry** — collects all model classes so `Base.metadata` knows every table
  (this is what Alembic autogenerate and `create_all` read),
- the **declarative mapping machinery** — turns class-level type hints into columns.

`Base.metadata` = the in-memory catalog of all tables/columns/indexes/constraints.

---

## 2. `Mapped[...]` + `mapped_column(...)` — declaring a column (the core pattern)

```python
name: Mapped[str] = mapped_column(String(128), nullable=False)
```
Two halves, two jobs:

- **`Mapped[str]`** — the **Python type** side. Tells SQLAlchemy + mypy + IDE that `agent.name` is a
  `str`. The type also implies nullability: `Mapped[str]` = non-null, `Mapped[str | None]` = nullable.
- **`mapped_column(...)`** — the **DB column** side: SQL type (`String(128)` → `VARCHAR(128)`) plus
  constraints (`nullable`, `unique`, `index`, `default`, `server_default`, `ForeignKey`, ...).

> Why split? `Mapped[...]` is for Python/typing; `mapped_column(...)` is for SQL/DB config. (In old
> 1.x you wrote `name = Column(String(128))` with no real typing.) The 2.0 split gives full static
> typing — the reason we can run strict mypy over models.

Keep the type and `nullable` in agreement:
```python
department: Mapped[Department | None] = mapped_column(department_enum, nullable=True)
```

---

## 3. `__tablename__`

```python
class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
```
Maps the class to a SQL table. Convention: plural, snake_case.

---

## 4. Column options we use

```python
id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
```
- `primary_key=True` → the PK.
- `PGUUID(as_uuid=True)` → Postgres-native `UUID`; work with Python `uuid.UUID` objects.
- `default=uuid4` → Python-side default; SQLAlchemy calls `uuid4()` per new row. (Pass the function
  `uuid4`, not `uuid4()`.)

```python
email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
```
- `unique=True` → `UNIQUE` constraint. `index=True` → B-tree index for fast lookup.

```python
status: Mapped[TicketStatus] = mapped_column(ticket_status_enum, nullable=False, default=TicketStatus.OPEN)
```
- `default=TicketStatus.OPEN` → new tickets start OPEN.

### `default` vs `server_default` (key distinction)
```python
created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), server_default=func.now(), nullable=False
)
updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
)
```
- `default=...` → applied by **Python** before INSERT.
- `server_default=...` → applied by the **database** (DDL says `DEFAULT now()`). Correct even if rows
  are inserted outside our app (a migration, raw SQL, another service).
- `onupdate=func.now()` → SQLAlchemy sets the column on every UPDATE → auto-updating `updated_at`.
- `func.now()` → SQLAlchemy's way to render the SQL `now()` function.

---

## 5. `TimestampMixin` — sharing columns (DRY)

```python
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(..., server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(..., server_default=func.now(), onupdate=func.now())

class Agent(Base, TimestampMixin):   # inherits both columns
    ...
```
A **mixin** is a plain class holding column definitions that multiple models inherit — a reusable
bundle of columns, so every table gets identical audit timestamps without copy-paste. Order matters:
`Base` gives the mapping machinery; `TimestampMixin` contributes columns.

---

## 6. `ForeignKey` — linking tables (the column side)

```python
assigned_agent_id: Mapped[UUID | None] = mapped_column(
    PGUUID(as_uuid=True),
    ForeignKey("agents.id", ondelete="SET NULL"),
    nullable=True,
)
```
- `ForeignKey("agents.id")` → this column references `agents.id`; the DB enforces the value must
  exist there (referential integrity).
- `ondelete="SET NULL"` → when the referenced agent is deleted, this becomes `NULL` (ticket
  unassigned, not deleted). Alternatives: `CASCADE` (delete child too), `RESTRICT` (block the delete).
- This is the actual **column** storing the agent's UUID.

---

## 7. `relationship(...)` — ORM navigation (NOT a column)

The confusing-but-crucial distinction:
- `assigned_agent_id` (ForeignKey) = the **column** storing a UUID.
- `assigned_agent` (relationship) = a **Python convenience** to load the whole related object.

```python
assigned_agent: Mapped[Agent | None] = relationship(lazy="joined")
```
- `ticket.assigned_agent` → the linked `Agent` object (SQLAlchemy queries for it).
- `lazy="joined"` → *when* to load: fetch via SQL JOIN in the same query. Alternatives: `"select"`
  (separate query on access), `"selectin"` (batch load). Controls the **N+1 query problem**.

```python
events: Mapped[list[TicketEvent]] = relationship(
    back_populates="ticket", cascade="all, delete-orphan", order_by="TicketEvent.created_at",
)
```
- `Mapped[list[TicketEvent]]` → one-to-many (one ticket → many events).
- `back_populates="ticket"` → the other side (`TicketEvent.ticket`) points back; SQLAlchemy keeps
  both in sync.
- `cascade="all, delete-orphan"` → delete the ticket → events go too; remove an event from the list
  → it's deleted (no orphans).
- `order_by=...` → events returned sorted.

```python
processing_result: Mapped[ProcessingResult | None] = relationship(
    back_populates="ticket", cascade="all, delete-orphan", uselist=False,
)
```
- `uselist=False` → one-to-one (single object, not a list).

### Mental model
```
assigned_agent_id  →  the COLUMN (stores a UUID)          ← in the DB
assigned_agent     →  the RELATIONSHIP (gives Agent obj)  ← Python convenience, no extra column
```
A relationship creates no column — it uses the existing FK to fetch related objects.

---

## 8. `__table_args__` — table-level constructs

```python
__table_args__ = (
    Index("ix_tickets_status", "status"),
    Index("ix_tickets_status_priority", "status", "priority"),   # composite
)
```
Column-level options go in `mapped_column` (e.g. `index=True`). Things spanning **multiple columns**
or needing explicit names go here: composite indexes, composite unique/check constraints. It's a
tuple of table-level objects.

---

## 9. `TYPE_CHECKING` imports — avoid circular imports

```python
if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.ticket_event import TicketEvent
```
Models reference each other for type hints (`Mapped[Agent | None]`). Importing at runtime would
cause circular-import crashes. `TYPE_CHECKING` is `False` at runtime but `True` for mypy, so these
imports exist only for type-checking. SQLAlchemy resolves relationships via string class names
(e.g. `"TicketEvent.created_at"`), so it doesn't need the runtime import.

---

## 10. `__repr__`

```python
def __repr__(self) -> str:
    return f"<Agent id={self.id} email={self.email!r} dept={self.department}>"
```
Plain Python (not SQLAlchemy magic) — controls how the object prints in logs/debugger.

---

## 11. Vocabulary map

| Thing | Side | Does |
|-------|------|------|
| `DeclarativeBase` | infra | root class; metadata registry |
| `__tablename__` | schema | table name |
| `Mapped[T]` | Python/typing | attribute type + nullability |
| `mapped_column(...)` | SQL/DB | column type + constraints |
| `default` vs `server_default` | who sets it | Python-side vs DB-side |
| `TimestampMixin` | reuse | shared columns via inheritance |
| `ForeignKey` | column | FK column + integrity + `ondelete` |
| `relationship(...)` | navigation | load related objects (no new column) |
| `back_populates` | sync | link two sides of a relationship |
| `cascade` | lifecycle | child fate on delete |
| `lazy` | performance | when related objects load (N+1) |
| `uselist=False` | shape | one-to-one |
| `__table_args__` | schema | multi-column indexes/constraints |
| `TYPE_CHECKING` | imports | type-only imports (no cycles) |

---

## 12. What's NOT here yet (comes in Phase 2)

This doc covers **declaring** the schema. The other half of SQLAlchemy is **using** it at runtime:
- `Session` — the unit of work (we have `session_scope` in `app/core/db.py`).
- `select(Ticket).where(...)` — the 2.0 query API.
- `session.add()`, `session.get()`, `session.commit()`, `session.scalars(...)`.
- pagination (`.limit().offset()`), filtering, counting.
You'll see these in the repository adapters in Phase 2.

---

## 13. Self-test

1. What do `Mapped[str]` and `mapped_column(...)` each contribute?
2. `default` vs `server_default` — who applies each, and why do we use `server_default` for timestamps?
3. What's the difference between `assigned_agent_id` and `assigned_agent`?
4. What does `cascade="all, delete-orphan"` do?
5. Why `uselist=False` on `processing_result`?
6. What problem does `lazy="joined"` address?
7. Why are some imports under `if TYPE_CHECKING:`?
8. When do you use `__table_args__` instead of options on `mapped_column`?
