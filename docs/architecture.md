# Architecture Overview

This document describes the architecture of the Universal Prompt Service.

## System Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Docker Compose                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────────────────┐   │
│  │   Redis     │◀───▶│  API        │◀───▶│  Browser Workers (1-20)    │   │
│  │   :6379     │     │  :4001      │     │  :4101 each                 │   │
│  └─────────────┘     └─────────────┘     └─────────────────────────────┘   │
│                             │                          │                    │
│                             ▼                          ▼                    │
│                      ┌─────────────┐           ┌─────────────┐             │
│                      │  Reverse    │           │   Proxy     │             │
│                      │  Proxy      │           │ Coordinator │             │
│                      │  (Caddy)    │           │   :4200     │             │
│                      └─────────────┘           └─────────────┘             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. API Service (NestJS)

The main API service built with NestJS framework.

**Responsibilities:**
- Accept prompt requests via REST API
- Queue jobs in Redis via BullMQ
- Process jobs through worker pool
- Return job status and results
- Health monitoring of all workers

**Key Modules:**
- `PromptModule` - Handles prompt submission and job management
- `WorkerModule` - Manages communication with browser workers
- `RedisModule` - Redis client for caching and queue
- `HealthModule` - Health check endpoints

**Port:** 4001 (configurable via `PORT` env)

### 2. Redis

Message broker and data store for BullMQ job queue.

**Used for:**
- Job queue storage
- Job results caching
- Worker state coordination
- Proxy block tracking

**Port:** 6379

### 3. Browser Workers (Python)

Headless Chrome instances controlled by Selenium/Puppeteer.

**Responsibilities:**
- Execute Google AI Mode searches
- Manage browser sessions and profiles
- Handle proxy rotation
- Detect and recover from blocks

**Port:** 4101 (each worker)

**Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/search` | POST | Execute search |
| `/tabs/search` | POST | Warmup search tab |
| `/browser/restart` | POST | Restart browser |
| `/session/refresh` | POST | Refresh session |

### 4. Proxy Coordinator

Centralized proxy management service.

**Responsibilities:**
- Distribute proxies across workers
- Track blocked proxies
- Rotate proxies on demand

**Port:** 4200

### 5. Reverse Proxy (Caddy/Nginx)

TLS termination and routing.

**Features:**
- HTTPS support
- Load balancing
- noVNC access for debugging

## Data Flow

### 1. Submit Prompt

```
Client                API                  Redis              Worker
  │                    │                    │                   │
  │ POST /prompts      │                    │                   │
  │───────────────────▶│                    │                   │
  │                    │ LPUSH job          │                   │
  │                    │───────────────────▶│                   │
  │                    │                    │                   │
  │ 202 { jobId }      │                    │                   │
  │◀───────────────────│                    │                   │
```

### 2. Process Job

```
Processor              Redis              Worker
  │                      │                   │
  │ BRPOP job            │                   │
  │◀─────────────────────│                   │
  │                      │                   │
  │ POST /search         │                   │
  │─────────────────────────────────────────▶│
  │                      │                   │
  │ { text, html }       │                   │
  │◀─────────────────────────────────────────│
  │                      │                   │
  │ SET result           │                   │
  │─────────────────────▶│                   │
```

### 3. Get Status

```
Client                API                  Redis
  │                    │                    │
  │ GET /jobs/:id      │                    │
  │───────────────────▶│                    │
  │                    │ GET job            │
  │                    │───────────────────▶│
  │                    │                    │
  │                    │ { status, result } │
  │                    │◀───────────────────│
  │                    │                    │
  │ { status, result } │                    │
  │◀───────────────────│                    │
```

## Job States

```
┌─────────┐     ┌────────────┐     ┌───────────┐
│ pending │────▶│ processing │────▶│ completed │
└─────────┘     └────────────┘     └───────────┘
                      │
                      ▼
                ┌──────────┐
                │  failed  │
                └──────────┘
```

| State | Description |
|-------|-------------|
| `pending` | Job is queued, waiting for processing |
| `processing` | Job is being processed by a worker |
| `completed` | Job finished successfully |
| `failed` | Job failed after all retries |

## Retry Logic

The service implements robust retry logic with exponential backoff:

1. **Quick Retries** - Try up to `RETRY_MAX_ATTEMPTS` times with exponential backoff
2. **Worker Failover** - If preferred worker fails, try other healthy workers
3. **Recovery Wait** - If all workers are unhealthy, wait up to `RETRY_WAIT_FOR_WORKER_MAX_MS`
4. **Health Checks** - Periodically check worker health during recovery wait

```
Attempt 1 ──▶ Fail ──▶ Wait 1s ──▶ Attempt 2 ──▶ Fail ──▶ Wait 2s ──▶ Attempt 3
                                                                          │
                                                                          ▼
                                                                    All failed?
                                                                          │
                                                              ┌───────────┴───────────┐
                                                              ▼                       ▼
                                                        Wait for healthy       Mark as failed
                                                        worker (up to 5min)
```

## Scaling

### Horizontal Scaling (Workers)

Add more browser workers by updating:

1. `.env` - Set `COMPOSE_PROFILES` and `WORKER_BASE_URLS`
2. Run `docker compose up -d`

Example for 5 workers:
```bash
COMPOSE_PROFILES=worker2,worker3,worker4,worker5
WORKER_BASE_URLS=http://browser-worker:4101,http://browser-worker-2:4101,http://browser-worker-3:4101,http://browser-worker-4:4101,http://browser-worker-5:4101
```

### Resource Requirements

| Component | CPU | Memory | Disk |
|-----------|-----|--------|------|
| API | 0.5 | 512MB | 100MB |
| Redis | 0.5 | 256MB | 1GB |
| Browser Worker | 1.0 | 2GB | 500MB |

## Security Considerations

1. **No secrets in logs** - Sensitive data is masked
2. **X-Request-Id required** - All requests must include correlation ID
3. **Input validation** - All inputs validated via class-validator
4. **Rate limiting** - Implement at reverse proxy level
5. **TLS** - Use reverse proxy for HTTPS in production
