#!/usr/bin/env bash
# Start the HOPEFX backend API server on port 8000 (development mode)
set -a
source .env 2>/dev/null || true
set +a

export DATABASE_URL="${DATABASE_URL:-sqlite:///hopefx.db}"
export APP_ENV="${APP_ENV:-development}"
export SECURITY_JWT_SECRET="${SECURITY_JWT_SECRET:-8b42590a4571b3b7a514d74910fc449a95fae63b5fc3fff1ba47e3a0782dc2ec}"
export CONFIG_ENCRYPTION_KEY="${CONFIG_ENCRYPTION_KEY:-vN056AXHY33Lm6oymn8tJ6Ip2r6Y5Ul5tLw9WnHsBt1nZFSQ}"
export REDIS_DISABLED="${REDIS_DISABLED:-true}"
export BROKER_TYPE="${BROKER_TYPE:-paper}"
export LOG_JSON="${LOG_JSON:-false}"
export LOG_ASYNC="${LOG_ASYNC:-false}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}"
export WEB_CONCURRENCY=1

# Disable optional heavy background services in dev
export ENABLE_GATEWAY="${ENABLE_GATEWAY:-false}"
export ENABLE_L2_FEED="${ENABLE_L2_FEED:-false}"
export ENABLE_NUCLEAR="${ENABLE_NUCLEAR:-false}"

exec uvicorn app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --log-level info \
  --timeout-keep-alive 30
