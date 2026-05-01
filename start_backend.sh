#!/usr/bin/env bash
# Start the HOPEFX backend API server on port 8000 (development mode)
set -a
# Load .env from repo root (secrets stay out of git)
source "$(dirname "$0")/.env" 2>/dev/null || true
set +a

# Defaults — .env values take precedence via set -a above
export DATABASE_URL="${DATABASE_URL:-sqlite:///./hopefx.db}"
export APP_ENV="${APP_ENV:-development}"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
export REDIS_DISABLED="${REDIS_DISABLED:-true}"
export BROKER_TYPE="${BROKER_TYPE:-paper}"
export PAPER_STARTING_BALANCE="${PAPER_STARTING_BALANCE:-100000}"
export LOG_JSON="${LOG_JSON:-false}"
export LOG_ASYNC="${LOG_ASYNC:-false}"
export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}"
export WEB_CONCURRENCY=1

# Disable optional heavy background services in dev
export ENABLE_GATEWAY="${ENABLE_GATEWAY:-false}"
export ENABLE_L2_FEED="${ENABLE_L2_FEED:-false}"
export ENABLE_NUCLEAR="${ENABLE_NUCLEAR:-false}"
export ENABLE_GRAPHQL="${ENABLE_GRAPHQL:-false}"
export ENABLE_CELERY="${ENABLE_CELERY:-false}"

exec uvicorn app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --log-level info \
  --timeout-keep-alive 30
