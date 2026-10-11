# Hook Relay API

A high-throughput, fault-tolerant webhook ingestion, verification, and dispatch engine built with **FastAPI**, **PostgreSQL**, **Redis**, and **Celery**.

Designed for enterprise workloads requiring guaranteed delivery, strict SSRF isolation, cryptographic payload verification, idempotency, and distributed rate limiting.

---

## Architecture & Core Features

```
                                  +-------------------+
                                  |   Client / API    |
                                  +---------+---------+
                                            |
                                            v (Bearer API Key)
                                 +--------------------+
                                 |    FastAPI API     |
                                 |  - Ingestion (202) |
                                 |  - Rate Limiter    |
                                 |  - Dual L1/L2 Auth |
                                 +----+----------+----+
                                      |          |
                     Event Ingestion  |          | Buffered Auth Flush
                     & Queue Broker   |          | & Token Buckets
                                      v          v
                               +--------------+  +---------------+
                               | Redis Broker |  | Redis Caching |
                               +------+-------+  +---------------+
                                      |
                       Dispatch Tasks |
                                      v
                             +-----------------+
                             |  Celery Workers |
                             |  + Beat Sched.  |
                             +---+--------+----+
                                 |        |
         HMAC Signed HTTP POST   |        | Async Persistence
         (Anti-SSRF Protection)  |        |
                                 v        v
                   +----------------+  +--------------------+
                   | External Hooks |  | PostgreSQL (Async) |
                   +----------------+  +--------------------+
```

- **Asynchronous Ingestion**: Ingests incoming events via `POST /api/v1/events` returning `202 Accepted` immediately with sub-millisecond overhead.
- **Deduplication & Idempotency**: Strict database-enforced event deduplication per tenant using `Idempotency-Key` headers.
- **Anti-SSRF Socket Transport**: Custom HTTPCore transport that resolves and pins IP addresses at connection time, blocking loopback, link-local, cloud metadata (`169.254.169.254`), and private RFC 1918 networks against DNS rebinding.
- **Cryptographic Webhook Signing**: Every delivery includes an `X-Webhook-Signature` (`t=<timestamp>,v<version>=<hmac_sha256>`). Signing secrets are Fernet-encrypted at rest with zero-downtime secret rotation.
- **Reliable Retry Engine**: Exponential backoff with Full Jitter, RFC-compliant `Retry-After` parsing, Dead Letter Queue (DLQ) state tracking, and manual replay support.
- **Stuck Delivery Reaper**: Periodic background scheduler (Celery Beat) automatically reclaims abandoned or timed-out worker deliveries.
- **Multi-Tier Token Bucket Rate Limiting**: Distributed Lua scripts in Redis enforcing granular limits for ingestion, reads, resource writes, and sensitive operations.
- **Dual-Layer Authentication Cache**: High-performance L1 (in-memory) + L2 (Redis) auth caching for API keys, with asynchronous bulk flushing of `last_used_at` timestamps to PostgreSQL.
- **Administrative CLI**: Built-in Typer CLI (`hook-relay-cli`) for tenant onboarding and API key generation.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Runtime & Language** | Python 3.13+, `uv` package manager |
| **Framework** | FastAPI, Starlette, Uvicorn (ASGI) |
| **Data Storage** | PostgreSQL 15+, SQLAlchemy 2.0 (Async), `asyncpg` |
| **Migrations** | Alembic |
| **Task Queue & Cache** | Redis 7+, Celery 5.6+, Kombu |
| **HTTP Transport** | HTTPX, HTTPCore (custom Anti-SSRF socket backend) |
| **Security & Crypto** | Cryptography (Fernet AES), HMAC-SHA256, Constant-time comparisons |
| **CLI & Formatting** | Typer, Rich, Orjson |
| **Testing** | Pytest, Pytest-Asyncio, Pytest-Cov, Pytest-Mock |

---

## Directory Layout

```
.
├── alembic/                # Database migrations & revision scripts
├── src/
│   ├── api/                # FastAPI routing & dependency injection
│   │   ├── deps.py         # Request-scoped dependencies & DB sessions
│   │   └── v1/routes/      # Endpoint, event, and delivery routes
│   ├── core/               # Core infrastructure logic
│   │   ├── config.py       # Pydantic v2 application settings
│   │   ├── http_client.py  # Anti-SSRF HTTP client factory
│   │   ├── pagination.py   # Page/limit pagination schemas
│   │   ├── rate_limit/     # Redis Lua token bucket rate limiting
│   │   ├── retry/          # Backoff, jitter, and retry policies
│   │   ├── security.py     # API key authentication & caching pipeline
│   │   └── ssrf.py         # Socket-level IP validation & subnet filters
│   ├── database/           # Async SQLAlchemy session and engine management
│   ├── infrastructure/     # Redis client, auth cache, and usage buffers
│   ├── models/             # SQLAlchemy ORM declarative models
│   ├── repositories/       # Data access layer (async repositories)
│   ├── schemas/            # Pydantic schemas for requests and responses
│   ├── services/           # Domain business logic (deliveries, events, endpoints)
│   ├── tasks/              # Celery task definitions (webhook runner, reaper, flusher)
│   ├── utils/              # Crypto utilities (signing, Fernet encryption, keys)
│   ├── cli.py              # System administration CLI tool
│   └── main.py             # FastAPI entrypoint, middleware, and health probes
├── tests/                  # Unit, API, and integration test suites
├── Makefile                # Task runner for dev, test, and worker operations
└── pyproject.toml          # Project metadata & dependency declarations
```

---

## Getting Started

### 1. Prerequisites

- Python `>= 3.13`
- [`uv`](https://docs.astral.sh/uv/) (recommended)
- PostgreSQL `>= 15`
- Redis `>= 7`

### 2. Environment Configuration

Copy the sample environment file and configure credentials:

```bash
cp .env.example .env
```

Ensure the following critical keys are set:

```env
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=hook_relay
DB_USERNAME=postgres
DB_PASSWORD=postgres

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Security Keys (Generate strong 32+ character secrets)
API_KEY_PEPPER=change-me-to-a-secure-key
ENDPOINT_SECRET_ENCRYPTION_KEY=change-me-to-a-secure-key
```

### 3. Installation & Database Setup

Install dependencies:

```bash
make install
# or for dev tools:
make dev-install
```

Run database migrations:

```bash
make migrate
```

### 4. Provision Initial Owner & API Key

Use the built-in administrative CLI to create a system owner and generate an API key:

```bash
# Create owner with a live or test API key
uv run hook-relay-cli create-owner --name "production-service" --env live

# Or output as machine-readable JSON for automated bootstrapping:
uv run hook-relay-cli create-owner --name "ci-service" --env test --json
```

> **Note:** Save the output API key (`hr_live_...` or `hr_test_...`). The secret is hashed with pepper and cannot be retrieved again.

---

## Running the Services

Hook Relay consists of three runtime components: the FastAPI HTTP service, Celery worker(s), and Celery Beat scheduler.

### 1. Web API Server
```bash
make run
# Runs: uv run uvicorn src.main:app --reload (defaults to http://127.0.0.1:8000)
```
- Interactive Docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 2. Celery Worker (Webhook Dispatcher)
```bash
make celery-worker
# Runs: uv run celery -A src.tasks.celery_app worker --loglevel=info
```

### 3. Celery Beat (Scheduler & Reaper)
```bash
make celery-beat
# Runs: uv run celery -A src.tasks.celery_app beat --loglevel=info
```
Celery Beat handles:
- Reaping zombie deliveries stuck in `delivering` state.
- Periodic flushing of cached API key usage timestamps to PostgreSQL.

---

## Running with Docker

Hook Relay API includes an optimized multi-stage Dockerfile producing a minimal footprint (~290MB), non-root container image.

### 1. Build the Docker Image
```bash
make docker-build
# Or directly:
docker build -t hook-relay-api:latest .
```

### 2. Run Database Migrations
Before starting the web server or workers, apply database migrations inside a container:
```bash
make docker-migrate
# Or directly:
docker run --rm -it --env-file .env hook-relay-api:latest alembic upgrade head
```

### 3. Start the Web API Server
```bash
make docker-run
# Or directly:
docker run --rm -it -p 8000:8000 --env-file .env --name hook-relay-web hook-relay-api:latest
```
Access the application at `http://localhost:8000`:
- **Liveness Probe**: `http://localhost:8000/health`
- **Readiness Probe**: `http://localhost:8000/ready`
- **Interactive Swagger Docs**: `http://localhost:8000/docs`

### 4. Start Celery Background Services
In separate terminal windows or as background processes:

**Celery Worker (Webhook Dispatcher):**
```bash
make docker-worker
# Or directly:
docker run --rm -it --env-file .env --name hook-relay-worker hook-relay-api:latest celery -A src.tasks.celery_app worker --loglevel=info
```

**Celery Beat (Periodic Scheduler & Reaper):**
```bash
make docker-beat
# Or directly:
docker run --rm -it --env-file .env --name hook-relay-beat hook-relay-api:latest celery -A src.tasks.celery_app beat --loglevel=info
```

### 5. Administrative CLI with Docker
Execute administrative commands inside a container:
```bash
# View CLI help:
make docker-cli cmd="--help"

# Create a tenant owner with an API key:
make docker-cli cmd="create-owner --name my-tenant --env live"

# Or directly:
docker run --rm -it --env-file .env hook-relay-api:latest hook-relay-cli --help
```

### 6. Clean Up Containers
Stop and remove all running project containers:
```bash
make docker-clean
```

---

## API Overview

All `/api/v1` routes require authentication via header: `Authorization: Bearer <API_KEY>`.

### Health & Diagnostics (Public)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service liveness probe |
| `GET` | `/ready` | Readiness probe (validates PostgreSQL and Redis connectivity) |
| `GET` | `/celery-health` | Worker cluster status via non-blocking control ping |

### Endpoints (`/api/v1/endpoints`)
| Method | Endpoint | Description | Rate Limit Tier |
|---|---|---|---|
| `POST` | `/api/v1/endpoints` | Register destination URL & generate signing secret | Writes (20 cap, 10/s) |
| `GET` | `/api/v1/endpoints` | List endpoints (paginated, filter by status) | Reads (40 cap, 20/s) |
| `GET` | `/api/v1/endpoints/{id}` | Retrieve endpoint configuration | Reads (40 cap, 20/s) |
| `PATCH` | `/api/v1/endpoints/{id}` | Update endpoint metadata or URL | Writes (20 cap, 10/s) |
| `DELETE` | `/api/v1/endpoints/{id}` | Soft-delete an endpoint | Writes (20 cap, 10/s) |
| `PATCH` | `/api/v1/endpoints/{id}/pause` | Pause deliveries to this endpoint | Writes (20 cap, 10/s) |
| `PATCH` | `/api/v1/endpoints/{id}/resume` | Resume deliveries | Writes (20 cap, 10/s) |
| `POST` | `/api/v1/endpoints/{id}/rotate-secret` | Rotate signing secret (generates new secret version) | Sensitive (5 cap, 1/s) |

### Events (`/api/v1/events`)
| Method | Endpoint | Description | Rate Limit Tier |
|---|---|---|---|
| `POST` | `/api/v1/events` | Ingest event & queue deliveries for all active endpoints | Ingest (100 cap, 50/s) |
| `GET` | `/api/v1/events` | List ingested events (paginated) | Reads (40 cap, 20/s) |
| `GET` | `/api/v1/events/{id}` | Get event status and payload details | Reads (40 cap, 20/s) |
| `GET` | `/api/v1/events/{id}/deliveries` | List all delivery attempts for an event | Reads (40 cap, 20/s) |

> **Tip:** Supply header `Idempotency-Key: <unique_uuid_or_id>` on `POST /api/v1/events` to prevent duplicate ingestion under network retries.

### Deliveries (`/api/v1/deliveries`)
| Method | Endpoint | Description | Rate Limit Tier |
|---|---|---|---|
| `GET` | `/api/v1/deliveries` | List deliveries (filter by event, endpoint, status) | Reads (40 cap, 20/s) |
| `GET` | `/api/v1/deliveries/{id}` | Retrieve delivery details & current state | Reads (40 cap, 20/s) |
| `GET` | `/api/v1/deliveries/{id}/attempts` | List historical HTTP attempt logs and timings | Reads (40 cap, 20/s) |
| `POST` | `/api/v1/deliveries/{id}/retry` | Manually re-dispatch a `dead_letter` delivery | Sensitive (5 cap, 1/s) |

---

## Webhook Verification (Consumer Guide)

Each outbound webhook request contains cryptographic verification headers:

```http
POST /your-webhook-receiver HTTP/1.1
Host: receiver.example.com
User-Agent: HookRelay/1.0
Content-Type: application/json
X-Webhook-ID: 7a6e1a90-3b47-41a2-b258-05e83921b72e
X-Webhook-Event-Type: invoice.created
X-Webhook-Timestamp: 2026-10-07T13:35:22.100Z
X-Webhook-Secret-Version: 1
X-Webhook-Signature: t=1791380122,v1=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
```

### Signature Verification Algorithm
1. Extract the timestamp (`t`) and signature (`v1`) from `X-Webhook-Signature`.
2. Construct the signed string: `${t}.${raw_request_body}`.
3. Compute the HMAC using **SHA-256** and your endpoint's signing secret (`whsec_...`).
4. Perform constant-time hex comparison against `v1`.
5. Optional: Validate that timestamp `t` is within acceptable tolerance (e.g. 5 minutes) to protect against replay attacks.

---

## Testing

The project uses `pytest` with markers dividing isolated unit tests from integration and API contract suites:

```bash
# Run entire test suite
make test

# Run isolated unit tests (no external services needed)
make test-unit

# Run API endpoint contract tests
make test-api

# Run integration tests
make test-integration

# Run tests with HTML and terminal coverage report
make test-cov
```

---

## Operational & Production Readiness

- **Database Connection Pooling**: Configured via environment variables (`DB_ASYNC_POOL_SIZE`, `DB_ASYNC_MAX_OVERFLOW`, `DB_POOL_PRE_PING=true`, `DB_POOL_RECYCLE=1800`) to avoid leaked connections in high-concurrency environments.
- **Worker Resource Management**: Celery workers maintain persistent async event loops (`get_worker_loop()`), preventing per-task loop teardown and reusing asyncpg connection pools.
- **Graceful Shutdown**: Worker shutdown signals safely dispose database engines and release HTTP client connection sockets.
- **Late Acknowledgment**: Tasks utilize `task_acks_late=True` ensuring tasks are requeued if a worker process crashes mid-flight.
- **Dead-Letter Handling**: Tasks that exceed max retries are cleanly moved to `dead_letter` state rather than dropped, allowing audit and manual replay via the API.
