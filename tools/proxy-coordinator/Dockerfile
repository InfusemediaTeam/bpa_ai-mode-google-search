FROM python:3.11-slim

WORKDIR /app

# Install dependencies

COPY requirements.txt .
RUN apt-get update && apt-get install -y curl \
	&& pip install --no-cache-dir -r requirements.txt \
	&& apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy coordinator code
COPY coordinator.py .

# Expose port
EXPOSE 4200

# Run coordinator
CMD ["python", "coordinator.py"]
