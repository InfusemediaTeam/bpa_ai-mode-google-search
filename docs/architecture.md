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

## Concurrency & Job Processing

### Bull Queue Concurrency

**Configuration:**
```typescript
const WORKER_CONCURRENCY = process.env.WORKER_BASE_URLS.split(',').length
@Process({ name: 'process', concurrency: WORKER_CONCURRENCY })
```

**Behavior:**
- Bull processes **N jobs simultaneously**, where N = number of configured workers
- Example: 3 workers → max 3 jobs processing at once
- Additional jobs wait in queue (FIFO)
- Single and bulk jobs compete fairly for processing slots

### Batch Processing

**Bulk prompts create individual jobs:**
```
POST /prompts/bulk with 5 prompts
  ↓
Creates 5 separate jobs with shared batchId
  ↓
All 5 jobs compete for worker slots
  ↓
Process in parallel (up to concurrency limit)
```

**Benefits:**
- No blocking of queue by large batches
- Fair competition with single prompts
- Parallel processing for efficiency
- Individual retry per prompt

**Job Metadata:**
```typescript
{
  prompt: string,
  worker?: number,        // Ignored - see note below
  batchId?: string,       // For grouping
  batchIndex?: number,    // Original order
  batchTotal?: number     // Total in batch
}
```

## Worker Selection & Retry Logic

**IMPORTANT:** The `worker` parameter is **ignored** in production. Dynamic load balancing is always used.

The service implements robust worker selection with **infinite retry**:

### Worker Selection Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    searchWithRetry()                            │
│                  (Infinite Retry Loop)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐                                          │
│  │ findFreeWorker() │◀────────────────────────────────┐        │
│  │ (parallel health │                                  │        │
│  │  check all)      │                                  │        │
│  └────────┬─────────┘                                  │        │
│           │                                            │        │
│           ▼                                            │        │
│    ┌──────────────┐     No      ┌──────────────┐      │        │
│    │ Free worker? │────────────▶│ Wait 2 sec   │──────┘        │
│    └──────┬───────┘             └──────────────┘               │
│           │ Yes                                                 │
│           ▼                                                     │
│    ┌──────────────┐                                            │
│    │ POST /search │                                            │
│    └──────┬───────┘                                            │
│           │                                                     │
│           ▼                                                     │
│    ┌──────────────────────────────────────────────┐            │
│    │                  Result?                      │            │
│    ├──────────────────────────────────────────────┤            │
│    │ ✓ Success (200)     → Return result          │            │
│    │ ✓ Empty (422)       → Return raw_text        │            │
│    │ ✗ Blocked (503)     → Retry (proxy rotates)  │            │
│    │ ✗ Busy (423)        → Retry (find another)   │            │
│    │ ✗ Timeout           → Retry (find another)   │            │
│    │ ✗ Other error       → Retry (find another)   │            │
│    └──────────────────────────────────────────────┘            │
│                                                                 │
│  Note: Loop continues until success or Bull timeout (60s)      │
└─────────────────────────────────────────────────────────────────┘
```

### Key Behaviors

| Scenario | Action | Job Fails? |
|----------|--------|------------|
| All workers busy (423) | Wait 2s, retry indefinitely | **No** (until Bull timeout) |
| Worker blocked by Google (503) | Worker rotates proxy, retry with another | **No** |
| Worker returns empty (422) | Return raw_text as result | **No** |
| Worker timeout | Retry with another worker | **No** |
| Bull timeout (60s) | Job fails after 3 attempts | **Yes** |

### Implementation Details

1. **Parallel Health Check** - All workers checked simultaneously via `/health`
2. **Free Worker Criteria** - `ok=true`, `busy=false`, `ready !== false`
3. **Dynamic Selection** - Always picks first available worker (no sticky assignment)
4. **Infinite Retry** - Loop continues until success or Bull timeout
5. **Race Condition** - Worker may become busy between health check and request (handled by retry)
6. **Bull Timeout** - 60 seconds per job, 3 retry attempts with exponential backoff

### Error Handling

**Worker Errors:**
- **503 + retry_other_worker** → Google blocked, worker rotates proxy
- **422 + empty_result** → Empty result (not an error, returns raw_text)
- **423 / busy** → Worker became busy, retry
- **Timeout** → Worker didn't respond, retry
- **Other** → Unknown error, retry

**Job Failures:**
- Bull timeout exceeded (60s)
- 3 retry attempts exhausted
- Unrecoverable processor error

## Performance Characteristics

### Throughput

**Maximum concurrent jobs = Number of workers**
- 3 workers → 3 jobs processing simultaneously
- 10 workers → 10 jobs processing simultaneously

**Effective throughput:**
```
Throughput = (Workers × Success Rate) / Avg Job Duration

Example:
- 3 workers
- 95% success rate
- 30s average job duration
= (3 × 0.95) / 30s
= 0.095 jobs/second
= ~5.7 jobs/minute
= ~342 jobs/hour
```

### Latency

**Job latency components:**
1. Queue wait time: 0s (if workers free) to ∞ (if all busy)
2. Worker selection: ~100-500ms (parallel health checks)
3. Search execution: 10-30s (typical)
4. Retry overhead: 2s per retry attempt

**Best case:** ~10s (immediate worker, fast search)
**Typical:** ~30s (some queue wait, normal search)
**Worst case:** 60s (Bull timeout)

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

**Concurrency automatically adjusts:**
- Adding workers increases Bull concurrency
- More jobs process simultaneously
- Linear throughput scaling (up to Redis limits)

### Resource Requirements

| Component | CPU | Memory | Disk |
|-----------|-----|--------|------|
| API | 0.5 | 512MB | 100MB |
| Redis | 0.5 | 256MB | 1GB |
| Browser Worker | 1.0 | 2GB | 500MB |

## Known Limitations

### 1. Ignored Worker Parameter
**Issue:** API accepts `?worker=N` but ignores it in `searchWithRetry()`
**Impact:** Cannot pin jobs to specific workers
**Workaround:** None - dynamic selection always used

### 2. Race Condition in Worker Selection
**Issue:** Worker may become busy between health check and request
**Impact:** Occasional 423 errors, retry overhead
**Mitigation:** Automatic retry handles this gracefully

### 3. Infinite Retry Loop
**Issue:** No circuit breaker, retries until Bull timeout
**Impact:** Jobs hang if all workers permanently down
**Mitigation:** Bull timeout (60s) eventually fails the job

### 4. Inefficient Batch Status Query
**Issue:** `getBatchStatus()` loads ALL jobs from Redis, filters in memory
**Impact:** O(N) complexity where N = total jobs in system
**Workaround:** Avoid with large job counts (>10,000)

### 5. No Rate Limiting
**Issue:** No API-level rate limiting
**Impact:** Possible abuse, Redis overload
**Mitigation:** Implement at reverse proxy level

### 6. No Job Prioritization
**Issue:** All jobs processed FIFO
**Impact:** Cannot expedite urgent jobs
**Workaround:** None currently

## Security Considerations

1. **No secrets in logs** - Sensitive data is masked
2. **X-Request-Id required** - All requests must include correlation ID
3. **Input validation** - All inputs validated via class-validator
4. **Rate limiting** - **Must implement at reverse proxy level**
5. **TLS** - Use reverse proxy for HTTPS in production
6. **Job TTL** - Results auto-deleted after 24 hours
