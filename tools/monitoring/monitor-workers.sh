#!/bin/bash
# Worker health monitor and auto-restart script.
# Monitors all browser workers and restarts them if unhealthy.

set -euo pipefail

LOG_PREFIX="[WORKER-MONITOR]"
DOCKER_COMPOSE_FILE="${DOCKER_COMPOSE_FILE:-docker-compose.yml}"
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"  # seconds

log() {
    echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') $*"
}

check_worker_health() {
    local worker_name="$1"
    local container_name="google-search-ai-$worker_name"
    
    # Check if container is running
    if ! docker ps --format "{{.Names}}" | grep -q "^$container_name$"; then
        log "WARN: Container $container_name is not running"
        return 1
    fi
    
    # Check health endpoint
    if ! docker exec "$container_name" python /app/healthcheck.py >/dev/null 2>&1; then
        log "FAIL: Health check failed for $worker_name"
        return 1
    fi
    
    log "OK: $worker_name is healthy"
    return 0
}

restart_worker() {
    local worker_name="$1"
    local container_name="google-search-ai-$worker_name"
    
    log "Restarting unhealthy worker: $worker_name"
    
    # Try graceful restart first
    if docker restart "$container_name"; then
        log "Successfully restarted $worker_name"
        
        # Wait for startup
        sleep 30
        
        # Verify it's healthy now
        if check_worker_health "$worker_name"; then
            log "Worker $worker_name is healthy after restart"
            return 0
        else
            log "ERROR: Worker $worker_name still unhealthy after restart"
            return 1
        fi
    else
        log "ERROR: Failed to restart $worker_name"
        return 1
    fi
}

monitor_workers() {
    log "Starting worker health monitoring (interval: ${CHECK_INTERVAL}s)"
    
    # Get list of active browser workers
    local workers=()
    while IFS= read -r line; do
        if [[ $line =~ google-search-ai-browser-worker ]]; then
            workers+=("${line#google-search-ai-}")
        fi
    done < <(docker ps --format "{{.Names}}" | grep browser-worker || true)
    
    if [[ ${#workers[@]} -eq 0 ]]; then
        log "No browser workers found running"
        return 0
    fi
    
    log "Found ${#workers[@]} workers: ${workers[*]}"
    
    # Check each worker
    local unhealthy_count=0
    for worker in "${workers[@]}"; do
        if ! check_worker_health "$worker"; then
            if restart_worker "$worker"; then
                log "Successfully recovered $worker"
            else
                log "Failed to recover $worker"
                ((unhealthy_count++))
            fi
        fi
    done
    
    if [[ $unhealthy_count -gt 0 ]]; then
        log "WARNING: $unhealthy_count workers remain unhealthy"
        return 1
    else
        log "All workers are healthy"
        return 0
    fi
}

main() {
    log "Worker Health Monitor started (PID: $$)"
    
    while true; do
        monitor_workers || true  # Continue even if some workers fail
        log "Next check in ${CHECK_INTERVAL} seconds..."
        sleep "$CHECK_INTERVAL"
    done
}

# Handle signals gracefully
cleanup() {
    log "Received signal, shutting down..."
    exit 0
}

trap cleanup TERM INT

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi