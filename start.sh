#!/usr/bin/env bash
# HOPEFX AI Trading - Quick-start script
# Usage:
#   ./start.sh                  # Development mode (auto-reload, source dirs only)
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
# Dev: open the readiness gate so SQLite-only setups serve immediately (prod keeps it on).
[ "$APP_ENV" = "development" ] && export STARTUP_GATE="${STARTUP_GATE:-false}"
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

# ── Reload configuration ──────────────────────────────────────────────────────
# Without --reload-dir uvicorn watches the entire project root, which causes
# spurious restarts whenever the self-healer writes data/heal_manifest.json,
# the antivirus writes security/yara_rules/hopefx_builtin.yar at startup, or
# log rotation touches files under logs/.
#
# Fix: restrict watching to source directories only and exclude non-source
# file types via --reload-include / --reload-exclude (watchfiles globs).
# Each flag must be repeated per value — uvicorn uses multiple=True for all
# three options.
#
# Source directories watched (must exist at startup):
#   .        — app.py, run.py, cli.py and other root-level entry points
#   api      — FastAPI routers
#   auth     — authentication
#   core     — middleware, startup, event bus
#   brokers  — broker connectors
#   cache    — Redis cache layer
#   data_layer — market data orchestrator
#   security — self-healer, antivirus (*.py changes only)
#   risk     — risk management
#   ml       — ML inference (not saved_models/)
#   strategies / strategy — trading strategies
#   execution — order execution
#   compliance — KYC/AML
#   news     — sentiment / geopolitical
#   market_data — order book, feeds
#   notifications — alerts
#   monitoring — health checks
#   templates  — Jinja2 HTML templates

NO_RELOAD=false
for arg in "$@"; do
    [ "$arg" = "--no-reload" ] && NO_RELOAD=true
done

# Build the uvicorn command as an array so quoting is handled correctly.
CMD=(uvicorn app:app --host "$API_HOST" --port "$API_PORT")

if [ "$NO_RELOAD" = false ]; then
    CMD+=(--reload)

    # Add --reload-dir for each source directory that exists.
    for dir in . api auth core brokers cache data_layer security risk ml \
                strategies strategy execution compliance news market_data \
                notifications monitoring templates data_feed events features \
                portfolio payments monetization social analytics audit; do
        [ -d "$dir" ] && CMD+=(--reload-dir "$dir")
    done

    # Watch only Python source files and HTML templates.
    # This means JSON/CSV/YARA/log writes inside watched dirs are ignored.
    CMD+=(--reload-include "*.py")
    CMD+=(--reload-include "*.html")

    # Belt-and-suspenders: explicitly exclude runtime-write file types and
    # directories even if they somehow end up inside a watched dir.
    CMD+=(--reload-exclude "*.json")
    CMD+=(--reload-exclude "*.csv")
    CMD+=(--reload-exclude "*.log")
    CMD+=(--reload-exclude "*.yar")
    CMD+=(--reload-exclude "*.yara")
    CMD+=(--reload-exclude "*.tmp")
    CMD+=(--reload-exclude "*.pkl")
    CMD+=(--reload-exclude "*.joblib")
fi

# Pass through any extra flags except --no-reload (already consumed above).
for arg in "$@"; do
    [ "$arg" != "--no-reload" ] && CMD+=("$arg")
done

exec "${CMD[@]}"
