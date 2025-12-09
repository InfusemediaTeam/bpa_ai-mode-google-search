#!/bin/bash
set -e

echo "[MONITOR] Starting Worker Health Monitor Service"
echo "[MONITOR] Check interval: ${CHECK_INTERVAL:-30} seconds"
echo "[MONITOR] Log level: ${LOG_LEVEL:-INFO}"

# Wait for Docker socket to be available
until [ -S /var/run/docker.sock ]; do
    echo "[MONITOR] Waiting for Docker socket..."
    sleep 2
done

echo "[MONITOR] Docker socket available, starting monitoring service"

# Start the Python monitoring service
exec python monitor-workers.py