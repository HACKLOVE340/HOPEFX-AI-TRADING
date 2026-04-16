#!/usr/bin/env bash
# HOPEFX AI Trading - Quick-start script
# Usage:
#   ./start.sh                  # Development mode (auto-reload, localhost:5000)
#   ./start.sh --port 8080      # Custom port
#   ./start.sh --no-reload      # Production-style (no hot-reload)
#   API_HOST=0.0.0.0 ./start.sh # Bind to all interfaces

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Dev bootstrap: generate .env + seed admin if not present ─────────────────
if [ ! -f ".env" ]; then
    echo "[INFO] .env not found — running dev bootstrap..."
    python scripts/bootstrap_dev.py
fi

# Load .env into the shell environment
set -a
# shellcheck disable=SC1091
[ -f .env ] && source .env
set +a

# ── Frontend build — auto-build if static/index.html is missing ──────────────
# The static/ directory is gitignored (build artifact). Build it automatically
# on first run so the server can serve the React SPA without a manual step.
if [ ! -f "static/index.html" ]; then
    echo "[INFO] Frontend not built — running 'npm run build' in frontend/..."
    if command -v npm >/dev/null 2>&1 && [ -f "frontend/package.json" ]; then
        (cd frontend && npm install --silent && npm run build) \
            && echo "[INFO] Frontend built successfully → static/" \
            || echo "[WARN] Frontend build failed — API will still start, but / will show no UI"
    else
        echo "[WARN] npm not found or frontend/package.json missing — skipping frontend build"
    fi
else
    echo "[INFO] Frontend already built (static/index.html exists)"
fi

# ── Environment defaults ─────────────────────────────────────────────────────
export APP_ENV="${APP_ENV:-development}"
export API_HOST="${API_HOST:-0.0.0.0}"
export API_PORT="${API_PORT:-8000}"

echo ""
echo "  HOPEFX AI Trading Framework"
echo "  ─────────────────────────────────────────────────"
echo "  Login:        http://localhost:${API_PORT}/login"
echo "  Dashboard:    http://localhost:${API_PORT}/paper-trading"
echo "  API Docs:     http://localhost:${API_PORT}/docs"
echo "  Health:       http://localhost:${API_PORT}/health"
echo "  ─────────────────────────────────────────────────"
echo ""

# ── Start server ─────────────────────────────────────────────────────────────
exec uvicorn app:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --reload \
    "$@"
