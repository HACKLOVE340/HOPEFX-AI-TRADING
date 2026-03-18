# Multi-stage production build
FROM python:3.11-slim-bookworm AS builder

# Build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.11-slim-bookworm AS production

# Runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r hopefx && useradd -r -g hopefx hopefx

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /root/.local /home/hopefx/.local
ENV PATH=/home/hopefx/.local/bin:$PATH

# Copy application
COPY --chown=hopefx:hopefx src/ ./src/
COPY --chown=hopefx:hopefx pyproject.toml .

# Switch to non-root
USER hopefx

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

ENTRYPOINT ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
