#!/usr/bin/env bash
# HOPEFX AI Trading — Development startup script (Linux/macOS/VPS)
# Usage: bash scripts/start_dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[HOPEFX]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Check Python ──────────────────────────────────────────────────────────────
python3 --version >/dev/null 2>&1 || error "Python 3 not found. Install Python 3.10+"

# ── Check Node ────────────────────────────────────────────────────────────────
node --version >/dev/null 2>&1 || error "Node.js not found. Install Node.js 20+"

# ── Create .env if missing ────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  warn ".env not found — running bootstrap to generate it..."
  python3 scripts/bootstrap_dev.py
fi

# ── Install Python deps ───────────────────────────────────────────────────────
info "Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q uvicorn[standard] fastapi sqlalchemy aiosqlite python-dotenv \
  "pydantic[email]" redis "python-jose[cryptography]" "passlib[bcrypt]" \
  python-multipart httpx aiohttp yfinance pandas numpy joblib xgboost PyJWT

# ── Install frontend deps ─────────────────────────────────────────────────────
info "Installing frontend dependencies..."
cd frontend && npm install --silent && cd ..

# ── Build frontend ────────────────────────────────────────────────────────────
info "Building frontend..."
cd frontend && npm run build && cd ..

# ── Bootstrap DB ─────────────────────────────────────────────────────────────
info "Bootstrapping database..."
python3 scripts/bootstrap_dev.py 2>/dev/null || true

# ── Start backend ─────────────────────────────────────────────────────────────
info "Starting FastAPI backend on http://localhost:8000 ..."
APP_ENV=development uvicorn app:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# ── Wait for backend ──────────────────────────────────────────────────────────
info "Waiting for backend to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    info "Backend is ready."
    break
  fi
  sleep 1
done

info ""
info "╔══════════════════════════════════════════════════════╗"
info "║  HOPEFX AI Trading — Development Server Running      ║"
info "║                                                       ║"
info "║  Backend API:  http://localhost:8000                  ║"
info "║  API Docs:     http://localhost:8000/docs             ║"
info "║  Frontend:     Served by FastAPI at /                 ║"
info "║                                                       ║"
info "║  Login:        http://localhost:8000/login            ║"
info "║  Superadmin:   superadmin@hopefx.io                   ║"
info "║  Trader:       trader@hopefx.io                       ║"
info "║                                                       ║"
info "║  Press Ctrl+C to stop                                 ║"
info "╚══════════════════════════════════════════════════════╝"

# ── Keep running ──────────────────────────────────────────────────────────────
trap "kill $BACKEND_PID 2>/dev/null; info 'Stopped.'" EXIT INT TERM
wait $BACKEND_PID
