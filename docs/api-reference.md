# API Reference

This document describes the REST API endpoints of the Universal Prompt Service.

## Base URL

```
https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher
```

API paths follow contract format: `/api/v{major}/{businessFlow}/{tool}/{action}`

## Authentication

All requests **must** include the `X-Request-Id` header for request correlation.

```http
X-Request-Id: a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

If the header is missing, the API will return `400 BAD_REQUEST`.

## Response Format

All responses follow the standard format:

```json
{
  "data": { ... },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "processingTimeMs": 45
  }
}
```

Error responses:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": { ... }
  },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

---

## Endpoints

### Submit Prompt

Submit a prompt for asynchronous processing.

```http
POST /api/v1/search-intelligence/searcher/prompts
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-Request-Id` | Yes | Request correlation ID |
| `Content-Type` | Yes | `application/json` |

**Query Parameters:**
| Parameter | Required | Description |
|-----------|----------|-------------|
| `worker` | No | Preferred worker ID (1-N) |

**Request Body:**
```json
{
  "prompt": "Your search prompt text here"
}
```

**Response:** `202 Accepted`
```json
{
  "data": {
    "jobId": "123"
  },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "processingTimeMs": 12
  }
}
```

**Example:**
```bash
curl -X POST https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/prompts \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: $(uuidgen)" \
  -d '{"prompt": "What is the email pattern for company.com?"}'
```

---

### Submit Bulk Prompts

Submit multiple prompts for bulk asynchronous processing. All prompts are processed in parallel.

```http
POST /api/v1/search-intelligence/searcher/prompts/bulk
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-Request-Id` | Yes | Request correlation ID |
| `Content-Type` | Yes | `application/json` |

**Query Parameters:**
| Parameter | Required | Description |
|-----------|----------|-------------|
| `worker` | No | Preferred worker ID (1-N) |

**Request Body:**
```json
{
  "prompts": [
    { "prompt": "First search query" },
    { "prompt": "Second search query" },
    { "prompt": "Third search query" }
  ]
}
```

**Validation:**
- Minimum: 1 prompt
- Maximum: 100 prompts
- Each prompt: max 10,000 characters

**Response:** `202 Accepted`
```json
{
  "data": {
    "batchId": "batch_1234567890_abc123",
    "jobIds": ["1", "2", "3"],
    "count": 3
  },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "processingTimeMs": 45
  }
}
```

**Example:**
```bash
curl -X POST https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/prompts/bulk \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: $(uuidgen)" \
  -d '{
    "prompts": [
      { "prompt": "What is the email pattern for company.com?" },
      { "prompt": "What is the email pattern for example.org?" }
    ]
  }'
```

**Notes:**
- Each prompt creates a separate job that processes in parallel
- All jobs share the same `batchId` for tracking
- Jobs compete fairly with single prompts for worker resources
- Use the batch status endpoint to track overall progress

---

### Get Job Status

Get the status and result of a job by ID.

```http
GET /api/v1/search-intelligence/searcher/jobs/{jobId}
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-Request-Id` | Yes | Request correlation ID |

**Path Parameters:**
| Parameter | Description |
|-----------|-------------|
| `jobId` | Job ID returned from POST /prompts |

**Response:** `200 OK`
```json
{
  "data": {
    "jobId": "123",
    "status": "completed",
    "progress": {
      "stage": "processing",
      "workerId": 1
    },
    "result": {
      "text": "The email pattern for company.com is firstname.lastname@company.com",
      "html": "<div>...</div>",
      "usedWorker": 1
    },
    "error": null,
    "createdAt": "2024-01-01T12:00:00.000Z",
    "completedAt": "2024-01-01T12:00:05.000Z"
  },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "processingTimeMs": 5
  }
}
```

**Job Status Values:**
| Status | Description |
|--------|-------------|
| `pending` | Job is queued, waiting for processing |
| `processing` | Job is being processed by a worker |
| `completed` | Job finished successfully |
| `failed` | Job failed after all retries |

**Job Result Fields:**
| Field | Description |
|-------|-------------|
| `json` | JSON result from search (primary) |
| `raw_text` | Raw text content (fallback when json is empty) |
| `usedWorker` | Worker ID that processed the job |

**Error Response:** `404 Not Found`
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Job 123 not found"
  },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

**Example:**
```bash
curl https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/jobs/123 \
  -H "X-Request-Id: $(uuidgen)"
```

---

### Get Batch Status

Get aggregated status of all jobs in a batch.

```http
GET /api/v1/search-intelligence/searcher/batches/{batchId}
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-Request-Id` | Yes | Request correlation ID |

**Path Parameters:**
| Parameter | Description |
|-----------|-------------|
| `batchId` | Batch ID returned from POST /prompts/bulk |

**Response:** `200 OK`
```json
{
  "data": {
    "batchId": "batch_1234567890_abc123",
    "total": 10,
    "completed": 7,
    "processing": 2,
    "pending": 0,
    "failed": 1,
    "jobs": [
      {
        "jobId": "1",
        "status": "completed",
        "result": {
          "json": "...",
          "raw_text": "...",
          "usedWorker": 1
        },
        "error": null,
        "createdAt": "2024-01-01T12:00:00.000Z",
        "completedAt": "2024-01-01T12:00:05.000Z"
      }
    ]
  },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "processingTimeMs": 25
  }
}
```

**Error Response:** `404 Not Found`
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Batch batch_1234567890_abc123 not found"
  },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

**Example:**
```bash
curl https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/batches/batch_1234567890_abc123 \
  -H "X-Request-Id: $(uuidgen)"
```

**Notes:**
- Jobs are returned sorted by their original order in the batch
- Use this endpoint to monitor bulk operation progress
- Poll this endpoint instead of checking each job individually

---

### List Jobs

List all jobs with optional filtering and pagination.

```http
GET /api/v1/search-intelligence/searcher/jobs
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-Request-Id` | Yes | Request correlation ID |

**Query Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `status` | No | - | Filter by status (`pending`, `processing`, `completed`, `failed`) |
| `limit` | No | `50` | Items per page (max: 100) |
| `pageToken` | No | - | Pagination cursor |

**Response:** `200 OK`
```json
{
  "data": {
    "items": [
      {
        "jobId": "123",
        "status": "completed",
        "createdAt": "2024-01-01T12:00:00.000Z",
        "completedAt": "2024-01-01T12:00:05.000Z"
      },
      {
        "jobId": "124",
        "status": "processing",
        "createdAt": "2024-01-01T12:01:00.000Z"
      }
    ],
    "pagination": {
      "totalItems": 42,
      "itemsPerPage": 50,
      "nextPageToken": "eyJvZmZzZXQiOjUwfQ=="
    }
  },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "processingTimeMs": 15
  }
}
```

**Example:**
```bash
# Get all jobs
curl https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/jobs \
  -H "X-Request-Id: $(uuidgen)"

# Get only completed jobs
curl "https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/jobs?status=completed" \
  -H "X-Request-Id: $(uuidgen)"

# Paginate
curl "https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/jobs?limit=10&pageToken=eyJvZmZzZXQiOjEwfQ==" \
  -H "X-Request-Id: $(uuidgen)"
```

---

### Health Check

Check the health of the API and all workers.

```http
GET /api/v1/search-intelligence/searcher/health
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-Request-Id` | Yes | Request correlation ID |

**Response:** `200 OK`
```json
{
  "data": {
    "status": "ok",
    "app": "ok",
    "redis": "ok",
    "redisRttMs": 2,
    "workers": {
      "total": 3,
      "healthy": 3,
      "busy": 1,
      "status": "ok",
      "details": [
        {
          "id": 1,
          "ok": true,
          "busy": true,
          "ready": true,
          "browser": "chromium",
          "version": "143.0.7499.40",
          "chromeAlive": true,
          "error": null
        },
        {
          "id": 2,
          "ok": true,
          "busy": false,
          "ready": true,
          "browser": "chromium",
          "version": "143.0.7499.40",
          "chromeAlive": true,
          "error": null
        },
        {
          "id": 3,
          "ok": false,
          "busy": false,
          "ready": false,
          "browser": "chromium",
          "version": "143.0.7499.40",
          "chromeAlive": false,
          "error": "browser crashed or zombie"
        }
      ]
    },
    "timestamp": "2024-01-01T12:00:00.000Z"
  },
  "meta": {
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "processingTimeMs": 150
  }
}
```

**Status Values:**
| Status | Description |
|--------|-------------|
| `ok` | All workers healthy |
| `degraded` | Some workers unhealthy, but at least one is available |
| `fail` | No healthy workers |

**Worker Detail Fields:**
| Field | Description |
|-------|-------------|
| `ok` | Worker can accept requests |
| `busy` | Currently processing a request |
| `ready` | Warmup completed and browser alive |
| `chromeAlive` | Browser process is running (not crashed/zombie) |
| `error` | Error message if `ok: false` (e.g., "browser crashed or zombie") |

**Example:**
```bash
curl https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/health \
  -H "X-Request-Id: $(uuidgen)"
```

---

### List Log Files

List available log files.

```http
GET /api/v1/search-intelligence/searcher/logs/files
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-Request-Id` | Yes | Request correlation ID |

**Response:** `200 OK`
```json
{
  "data": {
    "logDir": "/usr/src/app/logs",
    "files": [
      {
        "name": "app-2025-12-11.log",
        "size": 13556,
        "modified": "2025-12-11T20:35:26.877Z"
      },
      {
        "name": "error-2025-12-11.log",
        "size": 0,
        "modified": "2025-12-11T20:29:18.042Z"
      }
    ]
  },
  "meta": {
    "requestId": "...",
    "processingTimeMs": 2
  }
}
```

**Example:**
```bash
curl https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/logs/files \
  -H "X-Request-Id: $(uuidgen)"
```

---

### Read Logs

Read application logs with filtering.

```http
GET /api/v1/search-intelligence/searcher/logs
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-Request-Id` | Yes | Request correlation ID |

**Query Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `type` | No | `app` | Log type: `app` or `error` |
| `date` | No | today | Date in YYYY-MM-DD format |
| `lines` | No | `100` | Number of lines from end (max: 10000) |
| `format` | No | `json` | Output format: `json` or `text` |

**Response (JSON format):** `200 OK`
```json
{
  "filename": "app-2025-12-11.log",
  "totalLines": 88,
  "returnedLines": 5,
  "logs": [
    {
      "context": "NestApplication",
      "level": "info",
      "message": "Nest application successfully started",
      "timestamp": "2025-12-11T20:35:26.871Z"
    }
  ]
}
```

**Response (text format):** `200 OK`
```
{"context":"NestApplication","level":"info","message":"Nest application successfully started","timestamp":"2025-12-11T20:35:26.871Z"}
```

**Error Response:** `404 Not Found`
```json
{
  "error": "Log file not found",
  "filename": "app-2025-12-10.log",
  "availableLogs": [
    {"name": "app-2025-12-11.log", "size": 13556, "modified": "2025-12-11T20:35:26.877Z"}
  ]
}
```

**Examples:**
```bash
# Read last 50 lines of app logs
curl "https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/logs?lines=50" \
  -H "X-Request-Id: $(uuidgen)"

# Read error logs for specific date
curl "https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/logs?type=error&date=2025-12-11" \
  -H "X-Request-Id: $(uuidgen)"

# Get logs as plain text
curl "https://ai-search.instagingserver.com/api/v1/search-intelligence/searcher/logs?format=text&lines=100" \
  -H "X-Request-Id: $(uuidgen)"
```

---

## Error Codes

| HTTP Status | Code | Description |
|-------------|------|-------------|
| 400 | `BAD_REQUEST` | Invalid request format or missing X-Request-Id |
| 401 | `UNAUTHORIZED` | Authentication failed |
| 403 | `FORBIDDEN` | Insufficient permissions |
| 404 | `NOT_FOUND` | Resource not found |
| 409 | `CONFLICT` | State conflict |
| 422 | `VALIDATION_ERROR` | Validation failed |
| 429 | `RATE_LIMITED` | Rate limit exceeded |
| 500 | `INTERNAL_ERROR` | Internal server error |
| 502 | `UPSTREAM_ERROR` | Worker or external service error |

---

## Swagger Documentation

Interactive API documentation is available at:

```
https://ai-search.instagingserver.com/api/docs
```
