# Learning: FastAPI Request Lifecycle (low-level) — `POST /api/v1/tickets`

> A full, low-level trace of one request through every layer of this app. This is the single most
> useful thing to internalize: master this and you'll design every endpoint the same disciplined way.
> Keyed to real code: `app/api/v1/tickets.py`, `app/services/ticket_service.py`,
> `app/repositories/`, `app/core/container.py`.

---

## Stage 0 — Transport (Uvicorn / ASGI), before your code

```
Client → raw HTTP bytes over TCP
      → UVICORN (ASGI server): parses HTTP into an ASGI scope + receive/send
      → FastAPI app (an ASGI callable)
```
Uvicorn is the ASGI **server**; FastAPI is an ASGI **app**. None of your code has run yet.

## Stage 1 — Middleware (onion: outer → inner → outer)

```
RequestIDMiddleware.dispatch():        # app/api/middleware.py
  • request_id = header X-Request-ID or uuid4()
  • request_id_ctx.set(request_id)     # ContextVar → every log line gets tagged
  • response = await call_next(request)  ── go inward ──►
  • response.headers["x-request-id"] = request_id   ◄── on the way back
```
Middleware wraps the whole request. Cross-cutting concerns (request-id, auth, logging) live here.

## Stage 2 — Routing + parameter resolution

```
Match METHOD+PATH: POST /api/v1/tickets → create_ticket()
FastAPI reads the endpoint SIGNATURE and resolves each parameter by TYPE:

  def create_ticket(payload: CreateTicketRequest, container: ContainerDep):
     payload   → from REQUEST BODY (Pydantic model)
     container → Annotated[Container, Depends(get_container)] → dependency injection
```
Key mechanic: **FastAPI decides where each argument comes from based on its type hint** (Pydantic
model → body; `Depends` → run+inject; Query/Path types → URL).

## Stage 3 — Input validation (DTO) — runs BEFORE your function body

```
raw JSON body
  → Pydantic validates against CreateTicketRequest:
       customer_email: EmailStr           (invalid → 422)
       priority: TicketPriority (enum)     (bad value → 422)
       subject: min_length=1, max_length=256
       ...
  → FAIL: RequestValidationError → exception handler → 422 envelope  (endpoint NEVER runs)
  → PASS: `payload` is a fully-typed, guaranteed-valid object
```
**Validation is automatic and happens before your code.** Inside the endpoint, `payload` is always
valid.

## Stage 4 — Dependency injection (the container)

```
Depends(get_container) → returns the singleton Container built at startup
   Container = { settings, ticket_repository, event_repository, ticket_service }
```
The container was assembled once at startup (composition root). The endpoint **receives** it wired;
it never constructs services itself. "Router calls the container" = it just reads
`container.ticket_service`.

## Stage 5 — Endpoint body (thin HTTP layer, NO business logic)

```python
def create_ticket(payload, container):
    ticket = container.ticket_service.create_ticket(payload)          # delegate
    data = TicketResponse.model_validate(ticket).model_dump(mode="json")  # ORM → out DTO
    return _envelope(data, 201, message="Ticket created")            # wrap + status
```

## Stage 6 — Service (domain core + Unit of Work)

```
TicketService.create_ticket(payload):
  with session_scope() as session:                # opens a transaction (Unit of Work)
     ticket = Ticket(customer_name=payload.customer_name, ..., status=OPEN)  # DTO → ORM
     self._tickets.create(session, ticket)         # calls the PORT (interface)
     self._events.add(session, TicketEvent(CREATED, to_status=OPEN, ...))    # audit row
     session.flush(); session.refresh(ticket)      # load DB-generated values (timestamps)
     session.expunge(ticket)                        # detach for use after session closes
  # scope exit → COMMIT both inserts atomically  (any exception → ROLLBACK)
```
Two essentials:
1. The service calls `self._tickets` / `self._events` = **ports**. It has no idea SQLAlchemy is
   behind them → swap the adapter, service unchanged.
2. `session_scope()` = **Unit of Work**: ticket INSERT + event INSERT are one atomic transaction.

## Stage 7 — Repository adapter (only place SQL lives)

```
SqlAlchemyTicketRepository.create(session, ticket):
   session.add(ticket)   # stage in the identity map
   session.flush()       # emit INSERT SQL now (inside the open transaction, NOT a commit)
   return ticket         # ticket.id now populated
```
Rule: **repositories `flush`, never `commit`. The service owns the transaction boundary.**

## Stage 8 — Response (ORM → DTO → envelope → JSON)

```
ticket (ORM, detached)
  → TicketResponse.model_validate(ticket)   # from_attributes=True reads ORM attrs
  → .model_dump(mode="json")                # UUID→str, datetime→ISO, enum→value
  → Envelope.ok(data=...)                   # {success, message, data, error, meta}
  → JSONResponse(status_code=201)
  → (back through middleware) x-request-id header added
  → Uvicorn writes HTTP 201 + JSON to client
```
**Three representations of "a ticket", kept separate on purpose:**
`CreateTicketRequest` (in) · `Ticket` ORM (stored) · `TicketResponse` (out).

---

## Full diagram

```
CLIENT ── HTTP POST /api/v1/tickets {json} ──►
UVICORN (ASGI: bytes → scope)
  ▼
RequestIDMiddleware ── set request_id (ContextVar) ───────────────┐
  ▼                                                               │
ROUTER create_ticket()                                            │
  ├─ payload → validate body vs CreateTicketRequest (DTO)         │
  │     └─ invalid → RequestValidationError → 422 envelope ✗      │
  ├─ container → Depends(get_container) → injected singleton      │
  ▼                                                               │
SERVICE create_ticket()                                           │
  │  with session_scope():        ← Unit of Work (transaction)    │
  │    Ticket(...) built from DTO fields                          │
  │    self._tickets.create() ─► PORT ─► SqlAlchemyTicketRepo → INSERT (flush)
  │    self._events.add()     ─► PORT ─► SqlAlchemyEventRepo  → INSERT (flush)
  │    refresh + expunge                                          │
  │  scope exit → COMMIT atomically (or ROLLBACK on error)        │
  ▼                                                               │
ROUTER ── TicketResponse.model_validate → model_dump             │
       ── Envelope.ok → JSONResponse(201)                         │
  ▼                                                               │
RequestIDMiddleware ── add x-request-id ◄─────────────────────────┘
  ▼
UVICORN writes HTTP 201 + JSON

Any AppError raised below the router (NotFoundError=404, InvalidTransitionError=409, …)
bubbles up to the registered exception handler → standard error envelope + status code.
```

---

## The mental checklist for ANY endpoint you build

1. **Transport** (Uvicorn/ASGI) — know it's there.
2. **Middleware** — cross-cutting (request-id, auth, logging); outer→inner→outer.
3. **Routing** — method+path → function.
4. **Input DTO** — Pydantic validates the body *before* your code (invalid → 422 automatically).
5. **Dependency injection** — `Depends` supplies wired collaborators; endpoint never constructs them.
6. **Endpoint = thin** — delegate to service, convert to out-DTO, wrap in envelope. No logic.
7. **Service = domain** — owns the transaction (UoW), calls **ports** (never concrete tech), enforces
   rules (state machine).
8. **Repository adapter** — only place SQL/ORM lives; `flush`, never `commit`.
9. **Three DTOs, not one** — request in, ORM stored, response out.
10. **Output** — ORM → response DTO → envelope → JSON, correct status code.
11. **Errors** — raise typed domain errors anywhere; one handler maps them to envelope+status. Never
    put HTTP status logic in the service.

---

## Why each boundary exists (interview answers)

- **Why a DTO instead of using the ORM model directly?** Decouples the public API contract from the
  DB schema; lets you validate input and control exactly what's exposed.
- **Why does the service own the transaction, not the repository?** A business operation may touch
  several repositories (ticket + event); they must commit together. The service is the natural
  atomic boundary (Unit of Work).
- **Why ports between service and DB?** So business logic depends on an interface, not SQLAlchemy —
  swappable + testable.
- **Why a single envelope + one exception handler?** Predictable client contract; error handling
  centralized instead of scattered across endpoints.
- **Why is the endpoint so thin?** Testability + reuse: the same service can be called from a worker,
  a CLI, or another endpoint without dragging HTTP concerns along.

---

## Self-test

1. At what stage is the request body validated, and what happens if it fails?
2. How does FastAPI decide where each endpoint parameter comes from?
3. Who opens/commits the DB transaction — router, service, or repository?
4. Why does the repository `flush()` but not `commit()`?
5. Name the three separate "ticket" representations and their roles.
6. Where does an `InvalidTransitionError` get turned into a 409, and how does it get there?
7. What does the RequestIDMiddleware do on the way in vs the way out?
