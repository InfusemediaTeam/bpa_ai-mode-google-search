# Configuration Guide

This document describes all configuration options for the Universal Prompt Service.

## Environment Variables

### Required Variables

These variables **must** be set. The application will fail to start without them.

| Variable | Description | Example |
|----------|-------------|---------|
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |
| `WORKER_BASE_URLS` | Comma-separated list of worker endpoints | `http://browser-worker:4101` |

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `4001` | API server port |
| `NODE_ENV` | `development` | Environment mode (`development`, `production`, `test`) |
| `LOG_DIR` | `./logs` | Directory for log files |

### Redis & Cache

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | - | Redis connection URL (required) |
| `CACHE_TTL_SEC` | `604800` | Cache TTL in seconds (7 days) |
| `JOB_RESULTS_TTL_SEC` | `86400` | How long to keep job results (24 hours) |

### Worker HTTP Timeouts

All timeouts are in milliseconds.

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_HEALTH_TIMEOUT_MS` | `7000` | Health check timeout |
| `WORKER_SEARCH_TIMEOUT_MS` | `30000` | Search request timeout |
| `WORKER_REFRESH_TIMEOUT_MS` | `15000` | Session refresh timeout |
| `WORKER_RESTART_TIMEOUT_MS` | `15000` | Browser restart timeout |
| `WORKER_WARMUP_TIMEOUT_MS` | `20000` | Tab warmup timeout |

### Bull Queue Timeouts

| Variable | Default | Description |
|----------|---------|-------------|
| `BULL_SEARCH_TIMEOUT_MS` | `60000` | Single search job timeout (1 min) |
| `BULL_BULK_TIMEOUT_MS` | `3600000` | Bulk job timeout (1 hour) |

### Retry Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RETRY_MAX_ATTEMPTS` | `3` | Max retry attempts before recovery mode |
| `RETRY_INITIAL_DELAY_MS` | `1000` | Initial delay between retries |
| `RETRY_MAX_DELAY_MS` | `30000` | Maximum delay (exponential backoff cap) |
| `RETRY_WAIT_FOR_WORKER_MAX_MS` | `300000` | Max time to wait for healthy worker (5 min) |
| `RETRY_HEALTH_CHECK_INTERVAL_MS` | `5000` | Health check interval during recovery |

### Docker Compose Profiles

| Variable | Description |
|----------|-------------|
| `COMPOSE_PROFILES` | Comma-separated list of worker profiles to enable |

Examples:
```bash
# 1 worker (default, no profile needed)
COMPOSE_PROFILES=

# 3 workers
COMPOSE_PROFILES=worker2,worker3

# 5 workers
COMPOSE_PROFILES=worker2,worker3,worker4,worker5

# 10 workers
COMPOSE_PROFILES=worker2,worker3,worker4,worker5,worker6,worker7,worker8,worker9,worker10
```

### Reverse Proxy / TLS

| Variable | Default | Description |
|----------|---------|-------------|
| `DOMAIN` | `localhost` | Domain name for TLS |
| `API_PORT` | `4001` | External API port |
| `NOVNC_PORT` | `3000` | noVNC port for browser debugging |
| `WATCHER_PORT` | `3101` | Watcher service port |
| `CERT_FULLCHAIN` | - | Path to TLS certificate |
| `CERT_PRIVKEY` | - | Path to TLS private key |

### Proxy Coordinator

| Variable | Default | Description |
|----------|---------|-------------|
| `COORDINATOR_URL` | `http://proxy-coordinator:4200` | Proxy coordinator URL |

---

## Browser Worker Configuration

These variables are used by Python browser workers (not NestJS API).

### Browser Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `BROWSER_URL` | `http://127.0.0.1:9222` | Chrome DevTools URL |
| `ATTACH_EXISTING` | `1` | Attach to existing browser |
| `USER_DATA_DIR` | `/data/chrome-profile` | Chrome profile directory |
| `PROFILE_DIRECTORY` | `Default` | Chrome profile name |
| `CHROME_EXECUTABLE` | - | Path to Chrome binary |
| `AUTO_REPAIR_BROWSER` | `1` | Auto-repair crashed browser |
| `HEADFUL` | `1` | Run with GUI |
| `HEADLESS` | `0` | Run headless |

### Python Worker Timeouts

All timeouts are in seconds.

| Variable | Default | Description |
|----------|---------|-------------|
| `PY_PAGE_TIMEOUT_SEC` | `45` | Page load timeout |
| `PY_ANSWER_TIMEOUT_SEC` | `20` | AI answer timeout |
| `PY_AI_READY_TIMEOUT_SEC` | `25` | AI ready state timeout |
| `PY_AI_READY_TIMEOUT_PER_SEARCH_SEC` | `8` | Per-search AI ready timeout |
| `PY_SEARCH_PAGE_OPEN_TIMEOUT_SEC` | `12` | Search page open timeout |
| `PY_NEW_SEARCH_BUTTON_WAIT_SEC` | `3` | New search button wait |
| `PY_QUIT_TIMEOUT_SEC` | `5` | Browser quit timeout |

### Proxy Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_LIST` | - | Comma-separated proxy list |
| `PROXY_URL` | - | Single proxy fallback |
| `PROXY_BINDING_MODE` | `independent` | `independent` or `by_profile` |
| `PROXY_ROTATION_REQUESTS` | `100` | Rotate proxy every N requests |
| `PROXY_BLOCK_TIMEOUT_SEC` | `3600` | Blocked proxy TTL (1 hour) |

### Session Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_PER_SEARCH` | `0` | Create new session per search |
| `MAX_SEARCHES_PER_SESSION` | `50` | Max searches before rotation |
| `USE_UC` | `0` | Use undetected-chromedriver |

---

## Configuration Examples

### Minimal Development Setup

```bash
# .env
REDIS_URL=redis://localhost:6379
WORKER_BASE_URLS=http://localhost:4101
PORT=4001
```

### Production with 5 Workers

```bash
# .env
NODE_ENV=production
REDIS_URL=redis://redis:6379
WORKER_BASE_URLS=http://browser-worker:4101,http://browser-worker-2:4101,http://browser-worker-3:4101,http://browser-worker-4:4101,http://browser-worker-5:4101
COMPOSE_PROFILES=worker2,worker3,worker4,worker5

# Increase timeouts for production
WORKER_SEARCH_TIMEOUT_MS=60000
BULL_SEARCH_TIMEOUT_MS=120000
RETRY_WAIT_FOR_WORKER_MAX_MS=600000

# TLS
DOMAIN=api.example.com
CERT_FULLCHAIN=/etc/letsencrypt/live/api.example.com/fullchain.pem
CERT_PRIVKEY=/etc/letsencrypt/live/api.example.com/privkey.pem
```

### High Availability (10 Workers)

```bash
# .env
COMPOSE_PROFILES=worker2,worker3,worker4,worker5,worker6,worker7,worker8,worker9,worker10
WORKER_BASE_URLS=http://browser-worker:4101,http://browser-worker-2:4101,http://browser-worker-3:4101,http://browser-worker-4:4101,http://browser-worker-5:4101,http://browser-worker-6:4101,http://browser-worker-7:4101,http://browser-worker-8:4101,http://browser-worker-9:4101,http://browser-worker-10:4101

# Aggressive retry settings
RETRY_MAX_ATTEMPTS=5
RETRY_WAIT_FOR_WORKER_MAX_MS=600000
```
