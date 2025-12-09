#!/bin/bash
set -e

# Clean stale X11 locks
rm -f /tmp/.X99-lock
pkill -f 'Xvfb :99' >/dev/null 2>&1 || true

# Start Xvfb
Xvfb :99 -screen 0 1920x1080x24 -ac &

# Wait for display to be ready
for i in $(seq 1 50); do
    if xdpyinfo -display :99 >/dev/null 2>&1; then
        break
    fi
    sleep 0.2
done

# Start VNC server
x11vnc -display :99 -forever -shared -nopw -rfbport 5901 -listen 0.0.0.0 -quiet &

# Start noVNC
${NOVNC_DIR}/utils/novnc_proxy --vnc localhost:5901 --listen 3001 &

# Periodic maintenance: clean Chromium profiles and caches in background
# Controlled by ENV:
#   CLEANUP_ENABLED (default 1)
#   CLEANUP_INTERVAL_MINUTES (default 120)
#   CLEANUP_MIN_AGE_MINUTES, CLEANUP_INCLUDE_ACTIVE_CACHES forwarded to script
if [ "${CLEANUP_ENABLED:-1}" = "1" ]; then
    (
        while true; do
            echo "[maintenance] Running cleanup_profiles.sh..."
            /app/maintenance/cleanup_profiles.sh || true
            # sleep for configured minutes
            interval_min=${CLEANUP_INTERVAL_MINUTES:-120}
            # Fallback to 120 if not an integer
            case "$interval_min" in
                ''|*[!0-9]*) interval_min=120 ;;
            esac
            sleep $(( interval_min * 60 ))
        done
    ) &
fi

# Start Python server (exec to replace shell with Python process)
echo "[ENTRYPOINT] Starting Python server (PID will be $$)"
echo "[ENTRYPOINT] If this message appears multiple times, container is restarting"
exec python /app/server.py
