# HOPEFX AI Trading Framework - Docker Configuration

FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    redis-tools \
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
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# Run the application
CMD ["python", "app.py"]
