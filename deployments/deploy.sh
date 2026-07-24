#!/usr/bin/env bash
# HOPEFX-AI-TRADING — VPS deploy script (runs ON the server)
# =============================================================================
# Called by .github/workflows/deploy.yml over SSH after `git reset --hard
# origin/main`, or run manually:  bash deployments/deploy.sh
#
# It rebuilds and (re)starts the Docker stack, then health-checks the API.
# Idempotent and safe to re-run.
#
# Env overrides (optional):
#   COMPOSE_FILE   compose file to use            (default: docker-compose.yml)
#   HEALTH_URL     health endpoint to poll        (default: http://localhost:8000/api/health/live)
#   HEALTH_RETRIES how many 3s polls before fail  (default: 40  → ~2 min)
#   COMPOSE_ARGS   extra args, e.g. a subset of services or a --profile
# =============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/api/health/live}"
HEALTH_RETRIES="${HEALTH_RETRIES:-40}"
COMPOSE_ARGS="${COMPOSE_ARGS:-}"

log() { echo "[deploy $(date -u +%H:%M:%S)] $*"; }

# ── Resolve the compose command (plugin `docker compose` or legacy binary) ────
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  log "ERROR: neither 'docker compose' nor 'docker-compose' is installed."
  exit 1
fi

log "repo:   $APP_DIR"
log "commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
log "compose: ${COMPOSE[*]} -f $COMPOSE_FILE"

# ── Pre-flight: a production .env must exist on the server (never committed) ───
if [ ! -f .env ]; then
  log "ERROR: .env not found in $APP_DIR."
  log "       Create it once on the server (copy from .env.example / .env.production.example"
  log "       and set APP_ENV=production, DATABASE_URL, REDIS_URL, ALLOWED_ORIGINS, secrets)."
  exit 1
fi

# ── Build + (re)start ─────────────────────────────────────────────────────────
log "building + starting containers (this can take a few minutes on first run)..."
# shellcheck disable=SC2086
"${COMPOSE[@]}" -f "$COMPOSE_FILE" up -d --build --remove-orphans $COMPOSE_ARGS

# ── Reclaim disk from old image layers ────────────────────────────────────────
log "pruning dangling images..."
docker image prune -f >/dev/null 2>&1 || true

# ── Health check ──────────────────────────────────────────────────────────────
log "waiting for API health at $HEALTH_URL ..."
for i in $(seq 1 "$HEALTH_RETRIES"); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    log "✅ healthy after ${i} checks. Deploy complete."
    exit 0
  fi
  sleep 3
done

log "⚠️  health check did NOT pass within ~$((HEALTH_RETRIES * 3))s."
log "    Recent logs:"
"${COMPOSE[@]}" -f "$COMPOSE_FILE" logs --tail=80 app 2>/dev/null || true
exit 1
