FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install Docker CLI for container management
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy monitoring scripts
COPY monitor-workers.py .
COPY entrypoint.sh .

RUN chmod +x entrypoint.sh

# Environment variables
ENV CHECK_INTERVAL=30
ENV LOG_LEVEL=INFO
ENV DOCKER_SOCKET=/var/run/docker.sock

# Health check for the monitor itself
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]