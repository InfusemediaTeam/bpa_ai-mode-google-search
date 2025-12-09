# API Reference

This document describes the REST API endpoints of the Universal Prompt Service.

## Base URL

```
http://localhost:4001/search-intelligence/searcher/v1
```

API paths follow n8n contract format: `/{businessFlow}/{tool}/v{major}/{action}`

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
POST /search-intelligence/searcher/v1/prompts
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
curl -X POST http://localhost:4001/search-intelligence/searcher/v1/prompts \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: $(uuidgen)" \
  -d '{"prompt": "What is the email pattern for company.com?"}'
```

---

### Get Job Status

Get the status and result of a job by ID.

```http
GET /search-intelligence/searcher/v1/jobs/{jobId}
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
curl http://localhost:4001/search-intelligence/searcher/v1/jobs/123 \
  -H "X-Request-Id: $(uuidgen)"
```

---

### List Jobs

List all jobs with optional filtering and pagination.

```http
GET /search-intelligence/searcher/v1/jobs
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
curl http://localhost:4001/search-intelligence/searcher/v1/jobs \
  -H "X-Request-Id: $(uuidgen)"

# Get only completed jobs
curl "http://localhost:4001/search-intelligence/searcher/v1/jobs?status=completed" \
  -H "X-Request-Id: $(uuidgen)"

# Paginate
curl "http://localhost:4001/search-intelligence/searcher/v1/jobs?limit=10&pageToken=eyJvZmZzZXQiOjEwfQ==" \
  -H "X-Request-Id: $(uuidgen)"
```

---

### Health Check

Check the health of the API and all workers.

```http
GET /search-intelligence/searcher/v1/health
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
          "browser": "chrome",
          "version": "120.0.0"
        },
        {
          "id": 2,
          "ok": true,
          "busy": false,
          "ready": true,
          "browser": "chrome",
          "version": "120.0.0"
        },
        {
          "id": 3,
          "ok": true,
          "busy": false,
          "ready": true,
          "browser": "chrome",
          "version": "120.0.0"
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

**Example:**
```bash
curl http://localhost:4001/search-intelligence/searcher/v1/health \
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
http://localhost:4001/api/docs
```
