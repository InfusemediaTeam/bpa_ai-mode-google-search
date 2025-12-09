# Deployment Guide

This document describes how to deploy the Universal Prompt Service.

## Prerequisites

- Docker & Docker Compose v2+
- At least 4GB RAM (more for multiple workers)
- Redis instance (included in docker-compose)

## Quick Start

### 1. Clone and Configure

```bash
# Clone repository
git clone <repository-url>
cd universal-prompt-service

# Copy environment file
cp .env.example .env

# Edit configuration
nano .env
```

### 2. Configure Workers

Edit `.env` to set the number of workers:

```bash
# For 3 workers:
COMPOSE_PROFILES=worker2,worker3
WORKER_BASE_URLS=http://browser-worker:4101,http://browser-worker-2:4101,http://browser-worker-3:4101
```

### 3. Start Services

```bash
# Start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f api
```

### 4. Verify

```bash
# Health check
curl http://localhost:4001/search-intelligence/searcher/v1/health \
  -H "X-Request-Id: test-123"

# Submit test prompt
curl -X POST http://localhost:4001/search-intelligence/searcher/v1/prompts \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: test-123" \
  -d '{"prompt": "test"}'
```

---

## Docker Compose Commands

### Start Services

```bash
# Start all services (detached)
docker compose up -d

# Start with specific compose file
docker compose -f docker-compose.yml up -d

# Start with direct access (no reverse proxy)
docker compose -f docker-compose.yml -f docker-compose.direct.yml up -d
```

### Stop Services

```bash
# Stop all services
docker compose down

# Stop and remove volumes (WARNING: deletes data)
docker compose down -v
```

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f browser-worker
docker compose logs -f redis
```

### Restart Services

```bash
# Restart all
docker compose restart

# Restart specific service
docker compose restart api
docker compose restart browser-worker
```

### Scale Workers

```bash
# Update .env with new COMPOSE_PROFILES and WORKER_BASE_URLS
# Then restart
docker compose up -d
```

### Rebuild Images

```bash
# Rebuild all
docker compose build

# Rebuild specific service
docker compose build api
docker compose build browser-worker

# Rebuild and start
docker compose up -d --build
```

---

## Development Mode

### Without Docker

```bash
# Install dependencies
npm install

# Start Redis locally
docker run -d -p 6379:6379 redis:alpine

# Start in development mode
npm run start:dev
```

### With Docker (Direct Access)

```bash
# Start with direct port access (no reverse proxy)
docker compose -f docker-compose.yml -f docker-compose.direct.yml up -d
```

This exposes:
- API: `http://localhost:4001`
- Browser Worker noVNC: `http://localhost:3001`
- Proxy Coordinator: `http://localhost:4200`

---

## Production Deployment

### 1. Environment Configuration

```bash
# .env
NODE_ENV=production
REDIS_URL=redis://redis:6379

# Workers
COMPOSE_PROFILES=worker2,worker3,worker4,worker5
WORKER_BASE_URLS=http://browser-worker:4101,http://browser-worker-2:4101,http://browser-worker-3:4101,http://browser-worker-4:4101,http://browser-worker-5:4101

# Timeouts (increase for production)
WORKER_SEARCH_TIMEOUT_MS=60000
BULL_SEARCH_TIMEOUT_MS=120000
RETRY_WAIT_FOR_WORKER_MAX_MS=600000

# TLS
DOMAIN=api.example.com
CERT_FULLCHAIN=/etc/letsencrypt/live/api.example.com/fullchain.pem
CERT_PRIVKEY=/etc/letsencrypt/live/api.example.com/privkey.pem
```

### 2. TLS Certificates

Using Let's Encrypt:

```bash
# Install certbot
apt install certbot

# Get certificate
certbot certonly --standalone -d api.example.com

# Certificates will be at:
# /etc/letsencrypt/live/api.example.com/fullchain.pem
# /etc/letsencrypt/live/api.example.com/privkey.pem
```

### 3. Start Production

```bash
docker compose up -d
```

### 4. Setup Auto-Renewal

```bash
# Add to crontab
0 0 * * * certbot renew --quiet && docker compose restart reverse-proxy
```

---

## Monitoring

### Health Endpoint

```bash
# Check health
curl http://localhost:4001/search-intelligence/searcher/v1/health \
  -H "X-Request-Id: monitor-$(date +%s)"
```

### Docker Stats

```bash
# Resource usage
docker stats

# Container status
docker compose ps
```

### Logs

```bash
# Follow all logs
docker compose logs -f

# Last 100 lines
docker compose logs --tail=100
```

---

## Troubleshooting

### API Not Starting

```bash
# Check logs
docker compose logs api

# Common issues:
# - REDIS_URL not set or Redis not running
# - WORKER_BASE_URLS not set
# - Port already in use
```

### Workers Not Responding

```bash
# Check worker logs
docker compose logs browser-worker

# Check worker health directly
curl http://localhost:4101/health

# Restart worker
docker compose restart browser-worker
```

### Redis Connection Failed

```bash
# Check Redis is running
docker compose ps redis

# Check Redis logs
docker compose logs redis

# Test connection
docker compose exec redis redis-cli ping
```

### Out of Memory

```bash
# Check memory usage
docker stats

# Reduce workers or increase host memory
# Each browser worker needs ~2GB RAM
```

### Browser Crashes

```bash
# Check worker logs for crash info
docker compose logs browser-worker | grep -i crash

# Restart browser via API
curl -X POST http://localhost:4101/browser/restart
```

---

## Backup & Restore

### Backup Redis Data

```bash
# Create backup
docker compose exec redis redis-cli BGSAVE
docker cp $(docker compose ps -q redis):/data/dump.rdb ./backup/

# Restore
docker cp ./backup/dump.rdb $(docker compose ps -q redis):/data/
docker compose restart redis
```

### Backup Logs

```bash
# Copy logs from container
docker cp $(docker compose ps -q api):/app/logs ./backup/logs/
```
