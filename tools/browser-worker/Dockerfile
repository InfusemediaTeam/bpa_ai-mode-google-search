# syntax=docker/dockerfile:1.7
# comments: English only
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build deps + runtime deps + Xvfb for headful in container + tini for zombie reaping
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev \
    wget gnupg ca-certificates \
    xvfb \
    x11vnc novnc websockify x11-utils \
    fonts-liberation fonts-noto-color-emoji \
    libnss3 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxrandr2 \
    libxkbcommon0 libxi6 libgtk-3-0 libdrm2 libgbm1 libasound2 libatk1.0-0 libatk-bridge2.0-0 \
    libxfixes3 libpango-1.0-0 libxcursor1 libxss1 \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Install distro Chromium (multi-arch friendly) and chromedriver for fallback
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends chromium chromium-driver; \
    rm -rf /var/lib/apt/lists/*

# App
WORKDIR /app
COPY requirements.txt /app/requirements.txt
# Install Python dependencies
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy refactored code structure
COPY browser/ /app/browser/
COPY search/ /app/search/
COPY session/ /app/session/
COPY server.py /app/server.py
COPY healthcheck.py /app/healthcheck.py
COPY healthcheck_server.py /app/healthcheck_server.py
COPY entrypoint.sh /app/entrypoint.sh
COPY maintenance/ /app/maintenance/
RUN chmod +x /app/entrypoint.sh
RUN chmod +x /app/maintenance/cleanup_profiles.sh

# Data dir for persistent Chrome profiles
VOLUME ["/data"]

# Default env
ENV DISPLAY=:99 \
    WORKER_PORT=4101 \
    WORKER_TIMEOUT_MS=10000 \
    CHROME_BINARY=/usr/bin/chromium \
    PY_WORKER_PROFILES=/data/.ai_mode_chrome_c,/data/.ai_mode_chrome_d

# Periodic cleanup defaults
ENV CLEANUP_ENABLED=1 \
    CLEANUP_INTERVAL_MINUTES=30 \
    CLEANUP_MIN_AGE_MINUTES=60 \
    CLEANUP_INCLUDE_ACTIVE_CACHES=0

EXPOSE 4101 3001 5901

# Use tini as PID 1 for proper signal handling and zombie process reaping
ENTRYPOINT ["/usr/bin/tini", "--"]

# Start Xvfb, VNC, noVNC, and Python server
ENV NOVNC_DIR=/usr/share/novnc
CMD ["/app/entrypoint.sh"]
