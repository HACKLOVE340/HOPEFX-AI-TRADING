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

# ── Encryption key (development fallback) ───────────────────────────────────
if [ -z "${CONFIG_ENCRYPTION_KEY:-}" ]; then
    echo "[WARN] CONFIG_ENCRYPTION_KEY not set – using built-in dev key."
    echo "       For production, export a real 32-char key:"
    echo "         export CONFIG_ENCRYPTION_KEY=\$(python -c \"import secrets; print(secrets.token_hex(32))\")"
    export CONFIG_ENCRYPTION_KEY="dev-key-minimum-32-characters-long-for-testing"
fi

# ── Environment defaults ─────────────────────────────────────────────────────
export ENVIRONMENT="${ENVIRONMENT:-development}"
export API_HOST="${API_HOST:-127.0.0.1}"
export API_PORT="${API_PORT:-5000}"

echo ""
echo "  HOPEFX AI Trading Framework"
echo "  ─────────────────────────────────────────────────"
echo "  API:          http://${API_HOST}:${API_PORT}/"
echo "  Docs:         http://${API_HOST}:${API_PORT}/docs"
echo "  Paper Trade:  http://${API_HOST}:${API_PORT}/paper-trading"
echo "  Pricing:      http://${API_HOST}:${API_PORT}/pricing"
echo "  ─────────────────────────────────────────────────"
echo ""

# ── Start server ─────────────────────────────────────────────────────────────
exec python cli.py start \
    --host "$API_HOST" \
    --port "$API_PORT" \
    "$@"
