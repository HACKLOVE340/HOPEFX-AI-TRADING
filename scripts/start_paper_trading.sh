#!/usr/bin/env bash
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
#
# start_paper_trading.sh
# ========================
# One-command launcher for the 30-day OANDA paper trading session.
#
# Prerequisites (run once before first launch):
#   1. Fill in .env:  OANDA_API_KEY, OANDA_ACCOUNT_ID, FINNHUB_API_KEY, FRED_API_KEY
#   2. python scripts/setup_db.py          (creates SQLite DB + runs migrations)
#   3. python scripts/verify_streaming.py  (confirms all feeds are wired)
#
# Usage:
#   chmod +x scripts/start_paper_trading.sh
#   ./scripts/start_paper_trading.sh
#
# Logs:
#   logs/paper_trading_YYYYMMDD_HHMMSS.log  — full session log (timestamped per run)
#   data/paper_trades.csv                   — trade-by-trade record
#   data/oanda_paper_start.json             — session anchor (balance, start time)
#
# Stop:
#   Ctrl+C  — graceful shutdown, closes all positions

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}"; }
fail() { echo -e "${RED}❌  $*${NC}"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        HOPEFX AI TRADING — Paper Mode Launcher       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── 1. Check .env exists ──────────────────────────────────────────────────────
if [[ ! -f "$ROOT/.env" ]]; then
    fail ".env not found. Copy .env.example → .env and fill in your API keys."
fi
ok ".env found"

# Load .env into shell
set -a
# shellcheck disable=SC1091
source "$ROOT/.env" 2>/dev/null || true
set +a

# ── 2. Check critical keys ────────────────────────────────────────────────────
MISSING_KEYS=()
[[ -z "${OANDA_API_KEY:-}" || "${OANDA_API_KEY:-}" == YOUR_* ]] && MISSING_KEYS+=("OANDA_API_KEY")
[[ -z "${OANDA_ACCOUNT_ID:-}" || "${OANDA_ACCOUNT_ID:-}" == YOUR_* ]] && MISSING_KEYS+=("OANDA_ACCOUNT_ID")

if [[ ${#MISSING_KEYS[@]} -gt 0 ]]; then
    fail "Missing required keys in .env: ${MISSING_KEYS[*]}"
fi
ok "OANDA credentials present"

# Warn about optional keys
[[ -z "${FINNHUB_API_KEY:-}" || "${FINNHUB_API_KEY:-}" == YOUR_* ]] && \
    warn "FINNHUB_API_KEY not set — live tick streaming disabled (signals will use REST polling)"
[[ -z "${FRED_API_KEY:-}" || "${FRED_API_KEY:-}" == YOUR_* ]] && \
    warn "FRED_API_KEY not set — macro features will use CSV fallback"

# ── 3. Check Redis ────────────────────────────────────────────────────────────
if redis-cli ping &>/dev/null; then
    ok "Redis running"
else
    warn "Redis not running — starting..."
    redis-server --daemonize yes --logfile /tmp/redis-hopefx.log 2>/dev/null || \
        warn "Could not start Redis — caching disabled"
fi

# ── 4. Database setup ─────────────────────────────────────────────────────────
ok "Running database setup..."
python3 scripts/setup_db.py 2>&1 | grep -E "✅|⚠️|❌|Running upgrade" || true

# ── 5. Verify streaming feeds ─────────────────────────────────────────────────
echo ""
echo "── Feed verification ──────────────────────────────────"
python3 scripts/verify_streaming.py 2>/dev/null || warn "Some feeds not configured — check output above"

# ── 6. Create log directory ───────────────────────────────────────────────────
mkdir -p "$ROOT/logs"
LOG_FILE="$ROOT/logs/paper_trading_$(date +%Y%m%d_%H%M%S).log"
ok "Logging to $LOG_FILE"

# ── 7. Launch ─────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Starting 30-day paper session on OANDA practice...  ║"
echo "║  Press Ctrl+C to stop gracefully                     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

exec python3 scripts/paper_trading_starter.py 2>&1 | tee "$LOG_FILE"
