# FastAPI Production Starter

A small task-management API that demonstrates backend fundamentals done carefully: authentication vs. authorization, validation, migrations, consistent errors, correlation IDs, structured logging, rate limiting, and a test suite that runs against a real PostgreSQL database.

> Portfolio project demonstrating secure API design and testable FastAPI architecture. Original code, synthetic data only.

## Features

- User registration and login (OAuth2 password flow, JWT bearer tokens, Argon2id password hashing)
- Task CRUD with validation, partial updates and offset pagination, filterable by status
- **Owner-only access:** users can read and modify only their own tasks, enforced in every SQL query
- Consistent JSON error envelope with a `request_id` on every error
- `X-Request-ID` correlation header on every response, bound to every log line
- Structured logs (JSON or console) with automatic redaction of password, token and secret fields
- Login rate limiting (Redis fixed window, atomic across API replicas)
- Liveness and readiness probes
- Alembic migrations, with a test that fails if models and migrations drift apart
- OpenAPI docs at `/docs`, with request examples

## Architecture

```mermaid
flowchart LR
    Client -->|HTTP + Bearer JWT| MW[RequestContextMiddleware<br/>request ID + access log]
    MW --> Routes[API routes<br/>api/routes/*]
    Routes --> Deps[Dependencies<br/>session, current user, rate limit]
    Routes --> Services[Services<br/>business rules + authorization]
    Services --> ORM[SQLAlchemy 2 async]
    ORM --> PG[(PostgreSQL)]
    Deps --> Redis[(Redis<br/>login rate limit)]
```

| Layer | Location | Responsibility |
|---|---|---|
| Config | `src/app/core/config.py` | Typed settings from env vars; rejects weak JWT secrets and sync DB drivers at startup |
| API | `src/app/api/` | HTTP concerns only: parsing, status codes, dependency wiring |
| Schemas | `src/app/schemas/` | Pydantic request/response models; `extra="forbid"` blocks mass assignment |
| Services | `src/app/services/` | Business logic and the ownership rule |
| Models | `src/app/models/` | SQLAlchemy tables, constraints and indexes |
| Core | `src/app/core/` | Security, errors, logging, middleware, rate limiting |

**Request flow** for `PATCH /api/v1/tasks/{id}`:

1. The middleware assigns a request ID.
2. FastAPI validates the path and body.
3. `get_current_user` decodes the JWT and loads the user. If authentication fails it returns 401; if the account is disabled, 403.
4. The service runs `SELECT … WHERE id = :id AND owner_id = :user`. No match returns 404.
5. The service applies only the fields that were sent, then commits.
6. The response is serialized through `TaskRead`.

## Authentication vs. authorization

- **Authentication** answers *who is calling?* `get_current_user` checks the JWT's signature, expiry and type, then loads the user. Failure returns **401** with `WWW-Authenticate: Bearer`.
- **Authorization** answers *are they allowed to do this?* The rule is that a task is visible to and changeable by its owner only. It lives in the service queries (`WHERE owner_id = :current_user`), so there is no code path that loads another user's task and then forgets to check. Another user's task returns **404, not 403**, so the API doesn't reveal that it exists. A valid token for a disabled account returns **403**.

## Technology choices

| Technology | Purpose | Trade-off / why |
|---|---|---|
| Python 3.14, FastAPI, Pydantic 2 | API + validation | Type-driven validation and OpenAPI for free. Python 3.15 was skipped because key dependencies don't yet ship 3.15 Windows wheels. |
| PostgreSQL 18 + SQLAlchemy 2 (async) + asyncpg | Persistence | Mature, strongly constrained storage. Async I/O avoids blocking the event loop on database calls. |
| Alembic | Migrations | Explicit, reviewable schema history. A naming convention gives constraints deterministic names. |
| UUIDv7 primary keys | IDs | Not guessable like serial integers, yet time-ordered, so B-tree inserts stay localized. Uses `uuid.uuid7()` from Python 3.14. |
| PyJWT (HS256) | Access tokens | Stateless and simple. Trade-off: tokens can't be revoked before they expire, so the lifetime is short (30 min). |
| pwdlib + Argon2id | Password hashing | A memory-hard algorithm, the current OWASP recommendation. Hashing runs in a thread pool so it doesn't block the event loop. |
| Redis | Login rate limit | Shared counter across replicas. An in-memory limiter would reset per process and be bypassable. |
| structlog | Logging | Structured key/value logs with context variables (request ID) and a redaction processor. |
| uv | Packaging | Fast, lockfile-based (`uv.lock`) reproducible installs. |
| Ruff, mypy (strict), pytest | Quality | One fast linter/formatter; strict typing on `src/`. |

## Requirements

- Python 3.14 (uv can install it: `uv python install 3.14`)
- [uv](https://docs.astral.sh/uv/) 0.13+
- PostgreSQL 16+ (developed against 18.6)
- Redis 7+, only if `RATE_LIMIT_ENABLED=true`
- Optional: Docker with Compose v2

## Local setup

```bash
git clone <your-repository-url>
cd fastapi-production-starter
uv sync                              # creates .venv and installs locked dependencies
cp .env.example .env                 # then edit: set JWT_SECRET_KEY and DATABASE_URL
uv run alembic upgrade head          # apply migrations
uv run uvicorn app.main:create_app --factory --reload --no-access-log
```

Open http://localhost:8000/docs. Use **Authorize** with an email and password you registered.

Without Redis, set `RATE_LIMIT_ENABLED=false` in `.env`.

### With Docker Compose

```bash
cp .env.example .env    # compose only needs JWT_SECRET_KEY from it
docker compose up --build
```

This starts Postgres 18, Redis 8, a one-shot `migrate` job and the API on port 8000. Compose binds host port 5432, so stop any other local Postgres first.

> **Status:** the Dockerfile and `compose.yaml` are written but have **not yet been verified**, because Docker isn't installed on the development machine yet.

## Configuration

| Variable | Required | Purpose | Example |
|---|---|---|---|
| `DATABASE_URL` | Yes | Async SQLAlchemy URL (`postgresql+asyncpg://` only) | `postgresql+asyncpg://postgres:postgres@localhost:5432/app` |
| `JWT_SECRET_KEY` | Yes | HS256 signing key, ≥ 32 chars | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No (30) | Token lifetime | `30` |
| `REDIS_URL` | No | Redis for rate limiting | `redis://localhost:6379/0` |
| `RATE_LIMIT_ENABLED` | No (true) | Toggle the login rate limit | `true` |
| `LOGIN_RATE_LIMIT` / `LOGIN_RATE_WINDOW_SECONDS` | No (5 / 60) | Attempts per window per client IP | `5` / `60` |
| `LOG_LEVEL` | No (INFO) | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `LOG_JSON` | No (true) | JSON logs (true) or readable console logs (false) | `false` locally |
| `TEST_DATABASE_URL` | Tests only | Database name **must end in `_test`** | `postgresql+asyncpg://postgres:postgres@localhost:5432/app_test` |

## API examples

These responses are real output from a local run, with only the token truncated.

```bash
# Register
curl -s -X POST localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"correct-horse-battery-staple"}'
```
```json
{"id":"01a13bc8-7c45-73d3-b7b0-d7491f71da9a","email":"ada@example.com","is_active":true,"created_at":"2026-10-14T18:59:17.190285Z"}
```

```bash
# Log in (OAuth2 password form: username = email)
curl -s -X POST localhost:8000/api/v1/auth/login \
  -d 'username=ada@example.com&password=correct-horse-battery-staple'
```
```json
{"access_token":"eyJhbGciOi...(truncated)","token_type":"bearer","expires_in":1800}
```

```bash
# Create a task (due_at offsets are normalized to UTC)
curl -s -X POST localhost:8000/api/v1/tasks -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Write the README","due_at":"2026-11-01T17:00:00+05:00"}'
```
```json
{"id":"01a13bc8-7e86-74b6-8fab-d2c3e4c67e87","title":"Write the README","description":null,"status":"todo","due_at":"2026-11-01T12:00:00Z","created_at":"2026-10-14T18:59:17.762152Z","updated_at":"2026-10-14T18:59:17.762152Z"}
```

```bash
# List (also: ?status=todo|in_progress|done, ?offset=)
curl -s "localhost:8000/api/v1/tasks?limit=10" -H "Authorization: Bearer $TOKEN"
```
```json
{"items":[{"id":"01a13bc8-7e86-74b6-8fab-d2c3e4c67e87","title":"Write the README","description":null,"status":"todo","due_at":"2026-11-01T12:00:00Z","created_at":"2026-10-14T18:59:17.762152Z","updated_at":"2026-10-14T18:59:17.762152Z"}],"total":1,"limit":10,"offset":0}
```

Every error, here a request with no token, uses the same envelope:
```
HTTP/1.1 401 Unauthorized
x-request-id: d1742ab4e0c14f9898c79f962db9ca50
{"error":{"code":"not_authenticated","message":"Not authenticated","details":null,"request_id":"d1742ab4e0c14f9898c79f962db9ca50"}}
```

Other endpoints: `GET/PATCH/DELETE /api/v1/tasks/{id}`, `GET /api/v1/users/me`, `GET /health/live`, `GET /health/ready`.

## Tests and quality checks

```bash
uv run pytest                 # 86 tests: unit + integration against real PostgreSQL
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run mypy                   # strict type checking of src/
uv run alembic check          # fails if models have changes with no migration
```

**How the integration tests work:**
- The suite creates `TEST_DATABASE_URL`'s database if it's missing. It then drops and recreates its `public` schema and runs the real Alembic migrations, so every run also tests the migrations.
- Each test runs inside a transaction that is rolled back afterwards. The app's own commits become savepoints. This keeps tests isolated and fast without truncating tables.
- Redis is replaced with `fakeredis`, so no Redis server is needed for tests.
- As a safety guard, the suite refuses to run unless the database name ends in `_test`.

**What is covered:**
- Registration, login and token validation: expired, forged, `alg=none`, wrong type, deleted user, disabled user.
- Cross-user access: read, update, delete and list as another user.
- Unauthenticated access to every task endpoint.
- Validation errors, including that passwords are never echoed back.
- Pagination and filtering.
- Rate limiting, including failing open when Redis is down.
- Readiness when the database or Redis is down.
- The 500 handler not leaking exception text.
- Request-ID propagation and sanitization.
- Database constraints: unique email, status check, foreign key, cascade delete.
- Migration up/down round trip, and model/migration drift.

**CI:** `.github/workflows/ci.yml` runs lint, format check, mypy and tests against a Postgres 18 service container on pushes to `main` and on pull requests. It hasn't run yet, because the repository hasn't been pushed to GitHub.

## Design decisions and trade-offs

1. **The ownership check lives in the query, not after it.** `WHERE id = :id AND owner_id = :me` makes cross-user reads structurally impossible and returns 404 instead of 403. *Alternative:* load the task, then compare `owner_id`. That's easier to forget on a new endpoint, and a 403 confirms the task exists.
2. **Uniqueness comes from the database constraint, not a pre-check.** Registration inserts and catches `IntegrityError` → 409. A SELECT-then-INSERT check would race with a concurrent registration for the same email.
3. **Short-lived stateless JWTs, no refresh tokens.** This is simple and needs no session store. *Cost:* a stolen token works until it expires (30 min), and logout is client-side only. A production system would add refresh-token rotation or a revocation list.
4. **The rate limiter fails open.** If Redis is down, logins are allowed and a warning is logged. This favors availability. A bank might choose to fail closed instead.
5. **Status is stored as VARCHAR + CHECK, not a native Postgres ENUM.** Adding a status later is then a constraint change instead of an `ALTER TYPE` migration.
6. **Password hashing runs in a thread pool.** Argon2 deliberately burns CPU for tens of milliseconds. Running it on the event loop would stall every concurrent request during a login burst.

## Reliability and security notes

- Passwords are hashed with Argon2id and a per-hash salt, and are never logged or echoed in validation errors.
- Login returns the same error for "unknown email" and "wrong password". For an unknown email it also verifies against a dummy hash, so the two cases take a similar amount of time.
- JWT algorithm is pinned server-side (`HS256`), and the `sub`, `exp` and `iat` claims are required.
- `extra="forbid"` on input models prevents mass assignment, for example sending `owner_id`.
- Client-supplied `X-Request-ID` values are accepted only if they match `[A-Za-z0-9._-]{1,64}`, which prevents log injection.
- Unhandled exceptions return a generic 500 with the request ID. Details go only to the logs.
- Settings validation stops the app from starting with a short JWT secret or a non-async database driver.

## Limitations

This is a portfolio project, not a production deployment:

- **Tokens:** no refresh tokens, token revocation, email verification or password reset.
- **Account enumeration:** registration returns 409 for an existing email, which reveals that the account exists. A production signup flow would usually send an email in both cases instead.
- **Rate limiting:** login only, keyed by client IP. Behind a reverse proxy, uvicorn needs `--proxy-headers` and `--forwarded-allow-ips`, or every client shares one IP.
- **Pagination:** offset-based and capped at 10,000. Keyset pagination would scale better for deep pages.
- **Migrations:** run as a separate Compose job. Rolling deploys would need a migration strategy that keeps old and new code compatible.
- **Not done:** no HTTPS termination, CORS configuration, metrics or tracing. Docker and CI files haven't been verified yet (see above).
- **Timing protection** against user enumeration is approximate, not constant-time.

## Roadmap

- [ ] Verify the Docker Compose stack and the CI pipeline
- [ ] Refresh tokens with rotation and revocation
- [ ] Keyset pagination
- [ ] Prometheus metrics and OpenTelemetry tracing
- [ ] Rate-limit task-creation per user

## License

No license has been chosen yet. Add a LICENSE file before publishing if you want others to reuse this code.
