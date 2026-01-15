# Documentation Index

Welcome to the BPA AI Mode Google Search API documentation.

## Quick Links

- **[API Reference](./api-reference.md)** - Complete API endpoint documentation
- **[Architecture](./architecture.md)** - System design and components
- **[Configuration](./configuration.md)** - Environment variables and settings
- **[Deployment](./deployment.md)** - Deployment instructions
- **[API Contracts](./api-contracts.md)** - REST JSON contract standards
- **[Troubleshooting](./troubleshooting.md)** - Common issues and solutions

## What's New

### Bulk Processing Support
- **Endpoint**: `POST /api/v1/search-intelligence/searcher/prompts/bulk`
- Submit 1-100 prompts in a single request
- All prompts process in parallel
- Track progress via batch status endpoint

### Batch Status Tracking
- **Endpoint**: `GET /api/v1/search-intelligence/searcher/batches/{batchId}`
- Aggregated status of all jobs in a batch
- Real-time progress monitoring
- Jobs sorted by original order

## System Overview

### Architecture
```
Client → API (NestJS) → Bull Queue (Redis) → Processor → Workers (Puppeteer)
```

### Key Features
- **Asynchronous Processing** - Submit jobs, poll for results
- **Dynamic Load Balancing** - Automatic worker selection
- **Infinite Retry** - Jobs retry until success or timeout
- **Parallel Execution** - Multiple jobs process simultaneously
- **Health Monitoring** - Real-time worker status

### Concurrency Model
- **Bull Queue Concurrency** = Number of workers
- Example: 3 workers → 3 jobs process simultaneously
- Fair competition between single and bulk jobs
- FIFO queue for pending jobs

## Quick Start

### Submit Single Prompt
```bash
curl -X POST http://localhost:4001/api/v1/search-intelligence/searcher/prompts \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: $(uuidgen)" \
  -d '{"prompt": "What is the email pattern for company.com?"}'
```

Response:
```json
{
  "data": {
    "jobId": "123"
  }
}
```

### Submit Bulk Prompts
```bash
curl -X POST http://localhost:4001/api/v1/search-intelligence/searcher/prompts/bulk \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: $(uuidgen)" \
  -d '{
    "prompts": [
      {"prompt": "Query 1"},
      {"prompt": "Query 2"},
      {"prompt": "Query 3"}
    ]
  }'
```

Response:
```json
{
  "data": {
    "batchId": "batch_1234567890_abc123",
    "jobIds": ["1", "2", "3"],
    "count": 3
  }
}
```

### Check Job Status
```bash
curl http://localhost:4001/api/v1/search-intelligence/searcher/jobs/123 \
  -H "X-Request-Id: $(uuidgen)"
```

### Check Batch Status
```bash
curl http://localhost:4001/api/v1/search-intelligence/searcher/batches/batch_1234567890_abc123 \
  -H "X-Request-Id: $(uuidgen)"
```

### Check System Health
```bash
curl http://localhost:4001/api/v1/search-intelligence/searcher/health \
  -H "X-Request-Id: $(uuidgen)"
```

## Performance Characteristics

### Throughput
- **Formula**: `(Workers × Success Rate) / Avg Job Duration`
- **Example**: 3 workers, 95% success, 30s avg = ~342 jobs/hour

### Latency
- **Best case**: ~10s (immediate worker, fast search)
- **Typical**: ~30s (some queue wait, normal search)
- **Worst case**: 60s (Bull timeout)

### Scaling
- Linear throughput scaling with worker count
- Add workers by updating `WORKER_BASE_URLS` env variable
- Concurrency automatically adjusts

## Job Lifecycle

```
Created → Pending → Processing → Completed
                              ↘ Failed (after 3 retries)
```

**States:**
- `pending` - Queued, waiting for worker
- `processing` - Being processed by worker
- `completed` - Successfully finished
- `failed` - Failed after all retries

**TTL:** Jobs auto-deleted after 24 hours

## Error Handling

### Worker Errors (Auto-Retry)
- **503 Blocked** - Worker rotates proxy, retry
- **422 Empty** - Returns raw_text, job completes
- **423 Busy** - Retry with another worker
- **Timeout** - Retry with another worker

### Job Failures
- Bull timeout exceeded (60s)
- 3 retry attempts exhausted
- Unrecoverable processor error

## Known Limitations

1. **Ignored Worker Parameter** - `?worker=N` parameter is ignored, dynamic selection always used
2. **Race Condition** - Worker may become busy between health check and request (handled by retry)
3. **Infinite Retry** - No circuit breaker, retries until Bull timeout
4. **Inefficient Batch Query** - O(N) complexity, avoid with >10,000 total jobs
5. **No Rate Limiting** - Must implement at reverse proxy level
6. **No Prioritization** - All jobs processed FIFO

## Security

- **X-Request-Id required** - All requests must include correlation ID
- **Input validation** - All inputs validated via class-validator
- **No secrets in logs** - Sensitive data masked
- **Rate limiting** - Implement at reverse proxy level
- **TLS** - Use reverse proxy for HTTPS in production
- **Job TTL** - Results auto-deleted after 24 hours

## Monitoring

### Health Check
```bash
GET /api/v1/search-intelligence/searcher/health
```

Returns:
- App status
- Redis connectivity
- Worker health (all workers)
- Busy/healthy worker counts

### Logs
```bash
GET /api/v1/search-intelligence/searcher/logs?type=app&lines=100
GET /api/v1/search-intelligence/searcher/logs/files
```

### Metrics to Monitor
- Worker busy/healthy ratio
- Failed job count
- Redis memory usage
- Average job duration
- Queue depth

## Support

For issues or questions:

1. Check [Troubleshooting Guide](./troubleshooting.md)
2. Review [Architecture Documentation](./architecture.md)
3. Consult [API Reference](./api-reference.md)
4. Check application logs
5. Verify system health endpoint

## API Contract

All endpoints follow the standard contract:
- Path format: `/api/v{major}/{businessFlow}/{tool}/{action}`
- Response format: `{ data, error, meta }`
- Error format: `{ code, message, details }`
- Correlation: `X-Request-Id` header required

See [API Contracts](./api-contracts.md) for full specification.
