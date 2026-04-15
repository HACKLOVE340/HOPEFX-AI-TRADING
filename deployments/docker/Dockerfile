# Multi-stage production build
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

# Build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.11-slim-bookworm AS production

# Runtime dependencies (sorted alphabetically) and non-root user in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r hopefx && useradd -r -g hopefx hopefx

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /root/.local /home/hopefx/.local
ENV PATH=/home/hopefx/.local/bin:$PATH

# Copy application
COPY --chown=hopefx:hopefx . .

# Switch to non-root
USER hopefx

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["sh", "-c", "curl -f http://localhost:8000/health || exit 1"]

EXPOSE 8000

ENTRYPOINT ["python", "app.py"]
