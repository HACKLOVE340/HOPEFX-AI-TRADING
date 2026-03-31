# HOPEFX Trading System - Production Dockerfile

FROM python:3.11-slim AS builder

# Build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim

# Runtime dependencies (sorted alphabetically)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local

# Set environment
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

WORKDIR /app

# Copy application code
COPY . .

# Create necessary directories and set permissions in a single layer
RUN mkdir -p /app/logs /app/config /app/data \
    && chmod +x /app/main.py

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["sh", "-c", "curl -f http://localhost:8080/health || exit 1"]

# Expose ports
EXPOSE 8000 8080 8081

# Run application
CMD ["python", "-u", "main.py", "--mode=paper", "--env=production"]
