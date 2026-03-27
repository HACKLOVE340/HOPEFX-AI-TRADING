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
