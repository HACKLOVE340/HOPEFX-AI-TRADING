# HOPEFX AI Trading Framework - Docker Configuration

FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# libquickfix-dev: required to compile the quickfix C-extension (FIX protocol).
#   Without it `pip install quickfix` silently falls back to a stub or fails
#   at import time on first order submission.
# libpq-dev: required to compile psycopg2 against PostgreSQL.
# curl: used by the HEALTHCHECK command below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libquickfix-dev \
    libpq-dev \
    redis-tools \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create required directories and a non-root user
RUN mkdir -p logs data credentials \
    && useradd -m -u 1001 hopefx \
    && chown -R hopefx:hopefx /app

# Drop root before the process starts
USER hopefx

# Expose port (matches docker-compose.yml and API_PORT default)
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production
ENV API_PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${API_PORT}/health || exit 1

# Run the application
CMD ["python", "app.py"]
