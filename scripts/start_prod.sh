#!/usr/bin/env bash
# HOPEFX AI Trading — Production startup script (Linux VPS)
# Usage: bash scripts/start_prod.sh
#
# Prerequisites:
#   - .env file with all production values set (copy from .env.example)
#   - PostgreSQL running and DATABASE_URL set in .env
#   - Redis running and REDIS_URL set in .env
#   - Python 3.10+ and Node.js 20+ installed
#   - pip dependencies installed (pip install -r requirements.txt)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[HOPEFX]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Validate .env ─────────────────────────────────────────────────────────────
[ -f ".env" ] || error ".env not found. Copy .env.example to .env and fill in all values."

# Source .env for validation checks
set -a; source .env; set +a

[ -n "${SECURITY_JWT_SECRET:-}" ] || error "SECURITY_JWT_SECRET not set in .env"
[ -n "${CONFIG_ENCRYPTION_KEY:-}" ] || error "CONFIG_ENCRYPTION_KEY not set in .env"
[ -n "${DATABASE_URL:-}" ] || error "DATABASE_URL not set in .env"

# ── Install Python deps ───────────────────────────────────────────────────────
info "Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ── Build frontend ────────────────────────────────────────────────────────────
info "Building frontend for production..."
cd frontend
npm install --silent
npm run build
cd ..
info "Frontend built to static/"

# ── Run DB migrations ─────────────────────────────────────────────────────────
info "Running database migrations..."
python3 scripts/bootstrap_prod.py 2>/dev/null || \
  python3 -c "
import os; os.environ.setdefault('APP_ENV','production')
from database.connection import get_or_create_db_manager
from database.models import Base
mgr = get_or_create_db_manager()
if mgr: Base.metadata.create_all(mgr._engine)
print('Schema created.')
" || warn "Migration step skipped (run manually if needed)"

# ── Determine worker count ────────────────────────────────────────────────────
WORKERS="${WEB_CONCURRENCY:-$(python3 -c 'import os; print(min(4, (os.cpu_count() or 1) * 2 + 1))')}"
info "Starting $WORKERS uvicorn workers..."

# ── Start production server ───────────────────────────────────────────────────
exec uvicorn app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "$WORKERS" \
  --loop uvloop \
  --http httptools \
  --log-level info \
  --access-log \
  --proxy-headers \
  --forwarded-allow-ips "*"
