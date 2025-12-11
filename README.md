# Universal Prompt Service

A universal NestJS service for processing prompts via a pool of browser workers. The service accepts prompts via REST API, queues them for asynchronous processing, and returns results with job status tracking.

## Features

- **Async Processing** — Submit prompts and get job IDs immediately (202 Accepted)
- **Worker Pool** — Supports 1-20 browser workers with load balancing
- **Retry Logic** — Automatic retries with exponential backoff and worker failover
- **n8n Contract Compliant** — Standard API format with `X-Request-Id` correlation
- **Job Management** — Query job status, results, and history with pagination
- **Health Monitoring** — Real-time health checks for all workers
- **Swagger Docs** — Interactive API documentation at `/api/docs`

## Quick Start

### 1. Configure

```bash
cp .env.example .env
# Edit .env - set WORKER_BASE_URLS and COMPOSE_PROFILES
```

### 2. Start with Docker

```bash
# Start all services
docker compose up -d

# Or with direct port access (development)
docker compose -f docker-compose.yml -f docker-compose.direct.yml up -d
```

### 3. Verify

```bash
# Health check
curl http://localhost:4001/api/v1/search-intelligence/searcher/health \
  -H "X-Request-Id: test-$(date +%s)"
```

## API Overview

Base URL: `http://localhost:4001/api/v1/search-intelligence/searcher`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/prompts` | Submit prompt for processing |
| GET | `/jobs/{jobId}` | Get job status and result |
| GET | `/jobs` | List all jobs with pagination |
| GET | `/health` | Health check with worker status |
| GET | `/logs` | Read application logs |
| GET | `/logs/files` | List available log files |

**Required Header:** `X-Request-Id` (correlation ID)

### Example: Submit Prompt

```bash
curl -X POST http://localhost:4001/api/v1/search-intelligence/searcher/prompts \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: $(uuidgen)" \
  -d '{"prompt": "What is the email pattern for company.com?"}'
```

Response (202 Accepted):
```json
{
  "data": { "jobId": "123" },
  "meta": { "requestId": "...", "processingTimeMs": 12 }
}
```

### Example: Get Result

```bash
curl http://localhost:4001/api/v1/search-intelligence/searcher/jobs/123 \
  -H "X-Request-Id: $(uuidgen)"
```

Response:
```json
{
  "data": {
    "jobId": "123",
    "status": "completed",
    "result": { "text": "firstname.lastname@company.com", "usedWorker": 1 },
    "createdAt": "2024-01-01T12:00:00.000Z",
    "completedAt": "2024-01-01T12:00:05.000Z"
  },
  "meta": { "requestId": "...", "processingTimeMs": 5 }
}
```

## Configuration

Key environment variables (see `.env.example` for full list):

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | Yes | Redis connection URL |
| `WORKER_BASE_URLS` | Yes | Comma-separated worker endpoints |
| `PORT` | No | API port (default: 4001) |
| `COMPOSE_PROFILES` | No | Docker profiles for additional workers |

### Worker Scaling

```bash
# 3 workers
COMPOSE_PROFILES=worker2,worker3
WORKER_BASE_URLS=http://browser-worker:4101,http://browser-worker-2:4101,http://browser-worker-3:4101
```

## Development

```bash
# Install dependencies
npm install

# Start in development mode
npm run start:dev

# Build for production
npm run build
npm run start:prod
```

## Documentation

- [Architecture Overview](docs/architecture.md) — System design and data flow
- [Configuration Guide](docs/configuration.md) — All environment variables
- [API Reference](docs/api-reference.md) — Detailed endpoint documentation
- [Deployment Guide](docs/deployment.md) — Docker and production setup
- [API Contracts (n8n)](docs/api-contracts-n8n.md) — REST JSON contract standards

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│  API        │────▶│  Redis      │────▶│  Processor  │
│  (n8n/etc)  │     │  :4001      │     │  (BullMQ)   │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
      ▲                                                            │
      │                                                            ▼
      │                                                   ┌─────────────────┐
      │                                                   │ Browser Workers │
      │                                                   │ :4101 (1-20)    │
      │                                                   └────────┬────────┘
      │                                                            │
      └────────────────────────────────────────────────────────────┘
                              Result via job status
```

## License

UNLICENSED
