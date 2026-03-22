# =============================================================================
# STAGE 1: Python Dependencies Builder
# =============================================================================
FROM python:3.12-slim as python-builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    libssl-dev \
    cargo \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# =============================================================================
# STAGE 2: Dashboard Builder (Node.js)
# =============================================================================
FROM node:20-alpine as dashboard-builder

WORKDIR /dashboard

COPY dashboard/package*.json ./
RUN npm ci

COPY dashboard/ ./
RUN npm run build

# =============================================================================
# STAGE 3: Final Runtime Image
# =============================================================================
FROM python:3.12-slim as runtime

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy Python packages from builder
COPY --from=python-builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy built dashboard
COPY --from=dashboard-builder /dashboard/dist /app/static

# Create non-root user
RUN groupadd -r hopefx && useradd -r -g hopefx -d /app hopefx \
    && chown -R hopefx:hopefx /app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

USER hopefx

EXPOSE 8000 9090

ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
