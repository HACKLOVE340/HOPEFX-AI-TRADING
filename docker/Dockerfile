# Multi-stage build for HOPEFX v2
FROM python:3.12-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.12-slim as production

WORKDIR /app

# Copy only necessary artifacts
COPY --from=builder /root/.local /root/.local
COPY --from=builder /build .

# Ensure scripts are in PATH
ENV PATH=/root/.local/bin:$PATH

# Non-root user for security
RUN useradd -m -u 1000 hopefx && chown -R hopefx:hopefx /app
USER hopefx

# Copy application code
COPY --chown=hopefx:hopefx src/ ./src/
COPY --chown=hopefx:hopefx configs/ ./configs/
COPY --chown=hopefx:hopefx alembic/ ./alembic/
COPY --chown=hopefx:hopefx docker/entrypoint.sh .
COPY --chown=hopefx:hopefx docker/gunicorn.conf.py .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
