# Troubleshooting Guide

This document provides solutions to common issues and debugging strategies.

## Common Issues

### 1. Jobs Stuck in Pending State

**Symptoms:**
- Jobs remain in `pending` status indefinitely
- No jobs are being processed

**Possible Causes:**

#### A. All Workers Busy
```bash
# Check worker status
curl http://localhost:4001/api/v1/search-intelligence/searcher/health

# Look for:
{
  "workers": {
    "busy": 3,  # All workers busy
    "healthy": 3
  }
}
```

**Solution:** Wait for workers to complete current jobs, or scale up workers.

#### B. All Workers Down
```bash
# Check health endpoint
curl http://localhost:4001/api/v1/search-intelligence/searcher/health

# Look for:
{
  "workers": {
    "healthy": 0,  # No healthy workers
    "status": "fail"
  }
}
```

**Solution:**
1. Check worker logs: `docker compose logs browser-worker`
2. Restart workers: `docker compose restart browser-worker`
3. Check browser processes: Workers may have crashed Chrome instances

#### C. Redis Connection Issues
```bash
# Check Redis connectivity
curl http://localhost:4001/api/v1/search-intelligence/searcher/health

# Look for:
{
  "redis": "fail"
}
```

**Solution:**
1. Check Redis container: `docker compose ps redis`
2. Check Redis logs: `docker compose logs redis`
3. Restart Redis: `docker compose restart redis`

#### D. Bull Queue Processor Not Running
```bash
# Check API logs for processor initialization
docker compose logs api | grep "Processor initialized"

# Should see:
# Processor initialized with 3 workers, concurrency=3
```

**Solution:**
1. Restart API: `docker compose restart api`
2. Check for errors in startup logs

---

### 2. Jobs Failing with Timeout

**Symptoms:**
- Jobs fail after 60 seconds
- Error: "Job timeout"

**Causes:**
- All workers busy for extended period
- Workers stuck on difficult searches
- Worker health check failures

**Diagnosis:**
```bash
# Check job status
curl http://localhost:4001/api/v1/search-intelligence/searcher/jobs/{jobId}

# Check worker health
curl http://localhost:4001/api/v1/search-intelligence/searcher/health
```

**Solutions:**

1. **Increase timeout** (if searches legitimately take longer):
   ```bash
   # In .env
   BULL_SEARCH_TIMEOUT_MS=120000  # 2 minutes
   ```

2. **Scale up workers** to reduce queue wait time

3. **Check worker performance**:
   ```bash
   # Monitor worker logs
   docker compose logs -f browser-worker
   ```

---

### 3. Worker Returns Empty Results (422)

**Symptoms:**
- Job completes with `status: "completed"`
- Result has empty `json` field
- Only `raw_text` is populated

**This is NOT an error** - it's expected behavior when:
- Google returns no structured data
- Search results are not parseable
- Worker successfully scraped but couldn't extract JSON

**Diagnosis:**
```bash
# Check job result
curl http://localhost:4001/api/v1/search-intelligence/searcher/jobs/{jobId}

# Look for:
{
  "result": {
    "json": "",
    "raw_text": "Some text content...",
    "usedWorker": 1
  }
}
```

**Action:** Use `raw_text` as fallback data source.

---

### 4. Worker Blocked by Google (503)

**Symptoms:**
- Jobs retry multiple times
- Worker logs show "blocked" or "CAPTCHA"
- Error: "Worker blocked: This request is not supported"

**Diagnosis:**
```bash
# Check worker logs
docker compose logs browser-worker | grep -i "blocked\|captcha"

# Check worker health
curl http://localhost:4001/api/v1/search-intelligence/searcher/health
```

**Automatic Mitigation:**
- Worker automatically rotates proxy
- Job retries with another worker
- Eventually succeeds if other workers available

**Manual Solutions:**

1. **Restart affected worker** to force proxy rotation:
   ```bash
   docker compose restart browser-worker
   ```

2. **Check proxy coordinator**:
   ```bash
   curl http://localhost:4200/health
   ```

3. **Verify proxy pool** has available proxies

---

### 5. High Memory Usage

**Symptoms:**
- API/Worker containers using excessive memory
- OOM kills
- Slow performance

**Diagnosis:**
```bash
# Check container memory
docker stats

# Check Redis memory
docker compose exec redis redis-cli INFO memory
```

**Solutions:**

1. **Reduce job retention**:
   ```bash
   # In .env
   JOB_RESULTS_TTL_SEC=3600  # 1 hour instead of 24
   ```

2. **Clear old jobs manually**:
   ```bash
   docker compose exec redis redis-cli FLUSHDB
   ```

3. **Limit worker count** if memory constrained

4. **Increase container memory limits** in docker-compose.yml

---

### 6. Batch Status Query Slow

**Symptoms:**
- `GET /batches/{batchId}` takes >5 seconds
- High CPU usage during query

**Cause:** Inefficient O(N) filtering when many jobs exist

**Diagnosis:**
```bash
# Check total job count
curl http://localhost:4001/api/v1/search-intelligence/searcher/jobs | jq '.data.pagination.totalItems'
```

**Solutions:**

1. **Use individual job status** instead of batch status:
   ```bash
   # Query specific jobs
   for jobId in $jobIds; do
     curl http://localhost:4001/api/v1/search-intelligence/searcher/jobs/$jobId
   done
   ```

2. **Clean up old jobs** to reduce total count

3. **Avoid batch status queries** with >10,000 total jobs

---

### 7. Worker Parameter Ignored

**Symptoms:**
- Specify `?worker=2` but different worker processes job
- Cannot pin job to specific worker

**Explanation:** This is **expected behavior**. The `worker` parameter is ignored in `searchWithRetry()`.

**Why:** Dynamic load balancing always selects first available worker for optimal throughput.

**Workaround:** None. System designed for dynamic selection.

---

## Debugging Strategies

### Check System Health

```bash
# Overall health
curl http://localhost:4001/api/v1/search-intelligence/searcher/health | jq

# Expected output:
{
  "status": "ok",
  "redis": "ok",
  "workers": {
    "status": "ok",
    "healthy": 3,
    "busy": 1
  }
}
```

### Monitor Job Queue

```bash
# List pending jobs
curl "http://localhost:4001/api/v1/search-intelligence/searcher/jobs?status=pending" | jq

# List processing jobs
curl "http://localhost:4001/api/v1/search-intelligence/searcher/jobs?status=processing" | jq

# List failed jobs
curl "http://localhost:4001/api/v1/search-intelligence/searcher/jobs?status=failed" | jq
```

### Check Logs

```bash
# API logs
docker compose logs -f api

# Worker logs
docker compose logs -f browser-worker

# Redis logs
docker compose logs -f redis

# All logs with timestamps
docker compose logs -f --timestamps
```

### Inspect Redis Queue

```bash
# Connect to Redis
docker compose exec redis redis-cli

# Check queue length
LLEN bull:prompt:wait

# Check active jobs
LLEN bull:prompt:active

# Check completed jobs
ZCARD bull:prompt:completed

# Check failed jobs
ZCARD bull:prompt:failed
```

### Test Worker Directly

```bash
# Health check
curl http://localhost:4101/health

# Test search (replace with actual worker URL)
curl -X POST http://localhost:4101/search \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test query"}'
```

---

## Performance Optimization

### Increase Throughput

1. **Add more workers**:
   ```bash
   # In .env
   COMPOSE_PROFILES=worker2,worker3,worker4,worker5
   WORKER_BASE_URLS=http://browser-worker:4101,http://browser-worker-2:4101,...
   ```

2. **Optimize worker timeout**:
   ```bash
   WORKER_SEARCH_TIMEOUT_MS=25000  # Reduce if searches typically faster
   ```

3. **Reduce retry delays**:
   ```bash
   RETRY_DELAY_MS=500  # Faster retries (default: 1000)
   ```

### Reduce Latency

1. **Warmup workers** before heavy load:
   ```bash
   # Warmup all workers
   for i in {1..3}; do
     curl -X POST http://localhost:410$i/tabs/search
   done
   ```

2. **Pre-check worker health** before submitting jobs

3. **Use batch endpoint** for multiple prompts instead of individual requests

---

## Error Code Reference

| HTTP | Code | Meaning | Solution |
|------|------|---------|----------|
| 400 | BAD_REQUEST | Invalid request format | Check request body/headers |
| 404 | NOT_FOUND | Job/batch not found | Verify ID, check if expired (24h TTL) |
| 422 | VALIDATION_ERROR | Invalid input | Check prompt length (<10,000 chars) |
| 500 | INTERNAL_ERROR | Server error | Check API logs |
| 502 | UPSTREAM_ERROR | Worker error | Check worker health/logs |

---

## Recovery Procedures

### Full System Restart

```bash
# Stop all services
docker compose down

# Clear Redis data (optional, loses all jobs)
docker volume rm bpa_ai-mode-google-search_redis-data

# Start services
docker compose up -d

# Verify health
curl http://localhost:4001/api/v1/search-intelligence/searcher/health
```

### Worker Recovery

```bash
# Restart single worker
docker compose restart browser-worker

# Restart all workers
docker compose restart browser-worker browser-worker-2 browser-worker-3

# Force recreate workers
docker compose up -d --force-recreate browser-worker
```

### Redis Recovery

```bash
# Restart Redis
docker compose restart redis

# If corrupted, clear and restart
docker compose stop redis
docker volume rm bpa_ai-mode-google-search_redis-data
docker compose up -d redis
```

---

## Monitoring Checklist

Daily monitoring should include:

- [ ] Check health endpoint status
- [ ] Monitor worker busy/healthy ratio
- [ ] Review failed job count
- [ ] Check Redis memory usage
- [ ] Review error logs for patterns
- [ ] Verify job completion rate
- [ ] Monitor average job duration

---

## Getting Help

If issues persist:

1. **Collect diagnostics**:
   ```bash
   # Save health status
   curl http://localhost:4001/api/v1/search-intelligence/searcher/health > health.json
   
   # Save recent logs
   docker compose logs --tail=1000 > logs.txt
   
   # Save job list
   curl http://localhost:4001/api/v1/search-intelligence/searcher/jobs > jobs.json
   ```

2. **Check documentation**:
   - `docs/architecture.md` - System design
   - `docs/configuration.md` - Configuration options
   - `docs/api-reference.md` - API details

3. **Review code**:
   - `src/api/v1/search-intelligence/searcher/` - Main logic
   - `src/modules/worker/worker-client.service.ts` - Worker communication
