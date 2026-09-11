# Learning: Configuration & The 12-Factor Config Principle

> A standalone deep-dive on how this project handles configuration — and why it's the clean,
> production-grade approach. This is the concept behind `app/core/config.py`.
> If you understand this doc end to end, you can confidently discuss app configuration and secret
> management in an interview.

---

## 1. What is "12-Factor"?

The **Twelve-Factor App** is a methodology (published ~2011 by Heroku engineers) of twelve
principles for building modern, cloud-ready backend services that are easy to deploy, scale, and run
identically across environments (local / dev / staging / prod).

This doc is about **Factor III: Config** — *"Store config in the environment."*

Other factors this project already touches:
- **Factor II — Dependencies:** explicitly declared (`pyproject.toml`) and locked (`uv.lock`).
- **Factor III — Config:** `config.py` reading env vars. ← this doc
- **Factor X — Dev/prod parity:** local `.venv` on Python 3.12 mirrors the Docker image.
- **Factor XI — Logs:** structured JSON logs to stdout (logs as event streams, not files).

---

## 2. Factor III in one idea

> **Config is anything that varies between deployments** — DB URLs, credentials, ports, feature
> flags, log levels. It must live in the **environment**, never hardcoded in source.

Why: the **same code artifact** (the same Docker image) should run everywhere. Only the environment
changes. Local points `DATABASE_URL` at `localhost`; production points it at the real DB — but the
built image is byte-identical.

The three rules:
1. **Separate config from code** — no passwords/URLs baked into source (and no real `.env` in git).
2. **Config is per-environment** — same code, different env var values.
3. **No named "modes" in code** — avoid scattered `if env == "prod"` blocks; each setting is its own
   env var.

---

## 3. How it works in this project (`app/core/config.py`)

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )
    database_url: str = Field(default="postgresql+psycopg://...@localhost:5432/...")
    log_level: str = "INFO"
    environment: Literal["local", "dev", "stage", "prod"] = "local"
```

Each field in `Settings` is **one config knob**. On startup, pydantic-settings fills each field from
the environment, falling back to the default.

### Field name → env var name
- The field name maps to an env var of the **same name**.
- Because `case_sensitive=False`, `database_url` matches `DATABASE_URL`, `database_url`, `Database_Url`
  — all the same. Convention is UPPERCASE (`DATABASE_URL`).
- (Optional) you can decouple them with an alias: `Field(alias="DB_CONNECTION_STRING")`.

### Resolution order (per field)
```
Highest priority ───────────────────────────────► Lowest
Real env var   >   .env file   >   code default (fallback)
(prod/k8s/compose)   (local)         (safety net)
```
1. Env var matching the field name (case-insensitive)? → use it
2. In the `.env` file? → use it
3. Otherwise → use the code default

### Type coercion + validation (the real reason to use this over `os.environ`)
Env vars are always strings, but pydantic converts and validates them:
```python
db_pool_size: int = 5      # "DB_POOL_SIZE=10"  → int 10
db_echo: bool = False      # "DB_ECHO=true"     → bool True
environment: Literal[...]  # "ENVIRONMENT=production" (not allowed) → startup error
```
A malformed value fails **at startup with a clear error**, not deep inside a request later.

---

## 4. How Docker injects config

`docker-compose.yml`:
```yaml
api:
  environment:
    DATABASE_URL: postgresql+psycopg://ticketmaster:ticketmaster@db:5432/ticketmaster
```
Compose sets `DATABASE_URL` as a real OS env var inside the container. So `Settings()` finds it at
step 1 and uses `@db:5432`.

### Why `db` here but `localhost` in the code default?
- Inside Docker, Postgres is a *separate container* named `db`; Docker's network resolves `db` to it.
- On bare metal (no Docker), Postgres is at `localhost:5432`.

Different networking contexts → different hosts. The code default (`localhost`) is just the
first-run safety net; Docker overrides it via the env var.

> **Note (cleanup opportunity):** writing the URL in both `config.py` (default) and
> `docker-compose.yml` (value) is duplication. The cleaner pattern is Compose reading an `.env`
> file (`env_file: .env`) or `${DATABASE_URL}` references, so there's a single source of truth.

---

## 5. Deploying to a cluster (dev/stage/prod)

In a real cluster you **do not** ship `.env` files. The platform injects env vars into the container:

```
┌───────────────────────────────────────────────┐
│ Platform secret store                          │
│  • Kubernetes Secret (backed by Vault / AWS    │
│    Secrets Manager / Sealed Secrets)           │
│  • AWS ECS → Secrets Manager / SSM Parameter   │
│  • CI/CD → encrypted secrets                    │
└───────────────────┬───────────────────────────┘
                    │ injected as env vars into the pod/container
                    ▼
 same Docker image ─► container starts ─► Settings() reads env vars
 (built once)                              → typed, validated config
                                           → no secrets in code or git
```

So yes: on a dev cluster the env vars already exist on the server, and `Settings` loads them
automatically. **No code change between environments.** Rotating a secret is a platform change, not
a code change or rebuild.

---

## 6. The secret-management nuance (interview gold)

Be precise here — this is where interviews probe:

- **What this pattern gives you:** it *removes secrets from source code and git history*. The app
  reads them from the environment at runtime and doesn't care where they came from.
- **What provides the actual security:** the **platform's secret manager** (Vault, K8s Secrets, AWS
  Secrets Manager) that supplies those env vars. Env vars themselves are not "secure storage."

Accurate statement:
> "12-factor config removes secrets from code and lets the platform's secret manager supply them at
> runtime. The same image runs everywhere; rotating a secret needs no redeploy."

### Env-var weakness + guards (shows depth)
Env vars can leak via logs, error dumps, or process inspection. Guards:
- **Never log the whole `Settings` object** (it would print the DB URL *with password*).
- For very sensitive values, use pydantic's `SecretStr`, which masks the value in logs/reprs:
  ```python
  from pydantic import SecretStr
  db_password: SecretStr   # repr/logs show '**********', not the real value
  ```

---

## 7. Why not just `os.environ.get(...)`?

| Raw `os.environ` | Typed `Settings` (this project) |
|------------------|---------------------------------|
| Strings only; manual `int()`/`bool()` casts | Automatic type coercion |
| No validation; bad values crash later | Fail-fast validation at startup |
| Config scattered across the codebase | One central, documented place |
| Easy to typo a key with no warning | `Literal`/types catch typos immediately |
| No IDE autocomplete | Full autocomplete on `settings.database_url` |

---

## 8. The one-sentence takeaway

> **Externalize all config to environment variables; read them through a typed `Settings` class with
> sensible fallbacks (env → `.env` → default). In a cluster, the platform's secret manager injects
> those vars, so the same image runs everywhere, secrets never touch the codebase, and rotating them
> needs no redeploy.**

---

## 9. Self-test

1. What does "store config in the environment" mean, and why does it let one image run everywhere?
2. Given `case_sensitive=False`, which env var names match the field `database_url`?
3. What is the resolution order when `Settings` fills a field?
4. Why is `db` used in the Docker DB URL but `localhost` in the code default?
5. Env vars remove secrets from code — but what actually provides the *security*?
6. Name one way env vars can leak and how to guard a sensitive field.
7. Why prefer a typed `Settings` class over `os.environ.get("DATABASE_URL")`?

---

## 10. Precedence: pydantic Settings vs Docker Compose (don't mix them up)

Two different systems read configuration in this project, and **both follow the same precedence
direction**: the more runtime/explicit the source, the higher it wins.

| Priority | Pydantic `Settings` (app runtime) | Docker Compose `${VAR}` (YAML substitution) |
|----------|-----------------------------------|---------------------------------------------|
| 1 (highest) | real environment variable | shell/system environment variable |
| 2 | `.env` file | `.env` file (in the compose dir) |
| 3 (lowest) | code default (`Field(default=...)`) | `:-default` in the YAML (`${VAR:-default}`) |

> Common misconception: that Compose reads `.env` *before* the shell. It does **not** — the **shell
> environment wins over the `.env` file**, same as pydantic. Setting a var explicitly always beats a
> file, which always beats a baked-in default.

### Compose substitution example

`docker-compose.yml`: `POSTGRES_USER: ${POSTGRES_USER:-ticketmaster}`

- `.env` has `POSTGRES_USER=fromfile`, run `docker compose up` → **`fromfile`**
- `.env` has `POSTGRES_USER=fromfile`, run `POSTGRES_USER=fromshell docker compose up` → **`fromshell`** (shell wins)
- nothing set anywhere → **`ticketmaster`** (the `:-` default)

### `:-` vs `-` in Compose/shell substitution

| Syntax | Uses default when VAR is… |
|--------|---------------------------|
| `${VAR:-default}` | **unset OR empty** (safer — we use this) |
| `${VAR-default}` | **unset only** (an empty string is kept) |

### CRITICAL: two different files both named `.env`

Do not confuse these — they are separate mechanisms that happen to share a filename:

1. **Compose interpolation `.env`** — Compose auto-loads a `.env` in the compose directory to fill
   `${...}` placeholders *in the YAML itself* (e.g. which image tag, which port, which DB password to
   pass to the container). Shell env wins over it.
2. **Pydantic's `.env`** — the running app (`Settings`, via `env_file=".env"`) reads a `.env` to fill
   *its own* config fields at runtime.

In this project they can be the same file, but conceptually: Compose's `.env` configures **how the
containers are launched**; pydantic's `.env` configures **the app inside the container** (though in
Docker we usually pass those via the container's `environment:`, so real env vars — tier 1 — win).

### Why the direction is always "explicit beats file beats default"

So you can always override without editing tracked files. On a production server the platform
injects real env vars → they win over any committed `.env` or default. The environment has the final
say. That is the essence of 12-factor config.
