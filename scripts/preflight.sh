#!/usr/bin/env bash
# scripts/preflight.sh
# Production pre-flight checks for HOPEFX AI Trading.
#
# Runs before the API server starts (called by Dockerfile CMD or deploy.sh).
# Exits non-zero on any hard failure so the container/process does not start
# in a broken state.
#
# Usage:
#   ./scripts/preflight.sh              # full checks
#   SKIP_TESTS=true ./scripts/preflight.sh  # skip pytest (faster CI)
#   SKIP_MIGRATIONS=true ./scripts/preflight.sh  # skip alembic upgrade

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC}  $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC}  $*"; }
fail() { echo -e "${RED}  ✗${NC}  $*" >&2; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║       HOPEFX AI Trading — Pre-flight Checks          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── 1. Python version ─────────────────────────────────────────────────────────
# Dockerfile uses python:3.12-slim. Require 3.12+ in production to match.
echo "[ 1/8 ] Python version"
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "${PY_MAJOR}" -lt 3 ] || { [ "${PY_MAJOR}" -eq 3 ] && [ "${PY_MINOR}" -lt 12 ]; }; then
    fail "Python 3.12+ required (found $(python3 --version)). The Docker image uses python:3.12-slim."
fi
ok "Python $(python3 --version | cut -d' ' -f2)"

# ── 2. .env file ──────────────────────────────────────────────────────────────
echo "[ 2/8 ] Environment file"
if [ ! -f ".env" ]; then
    if [ "${APP_ENV:-development}" = "production" ]; then
        fail ".env not found in production. Copy .env.example and fill in all values."
    else
        warn ".env not found — running dev bootstrap"
        python3 scripts/bootstrap_dev.py || warn "Dev bootstrap failed (non-fatal in dev)"
    fi
fi

# Load .env into shell (skip comments and blank lines)
if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    ok ".env loaded"
fi

# ── 3. Required env vars ──────────────────────────────────────────────────────
echo "[ 3/8 ] Required environment variables"
MISSING=()
for VAR in SECURITY_JWT_SECRET DATABASE_URL REDIS_URL; do
    if [ -z "${!VAR:-}" ]; then
        MISSING+=("${VAR}")
    fi
done

if [ "${APP_ENV:-development}" = "production" ]; then
    for VAR in POSTGRES_PASSWORD REDIS_PASSWORD CRYPTO_WEBHOOK_SECRET HOPEFX_DOMAIN ALLOWED_ORIGINS; do
        if [ -z "${!VAR:-}" ]; then
            MISSING+=("${VAR}")
        fi
    done
fi

if [ ${#MISSING[@]} -gt 0 ]; then
    fail "Missing required env vars: ${MISSING[*]}"
fi
ok "All required env vars present"

# ── 4. Python dependencies ────────────────────────────────────────────────────
echo "[ 4/8 ] Python dependencies"
if ! python3 -c "import fastapi, sqlalchemy, alembic, uvicorn, redis, jwt, aiohttp" 2>/dev/null; then
    warn "Some dependencies missing — installing from requirements.txt"
    pip install -r requirements.txt --quiet || fail "pip install failed"
fi
# Hard-fail if uvicorn or aiohttp are still missing after install attempt
python3 -c "import uvicorn" 2>/dev/null || fail "uvicorn not installed — run: pip install 'uvicorn[standard]>=0.27.0'"
python3 -c "import aiohttp" 2>/dev/null || fail "aiohttp not installed — run: pip install 'aiohttp>=3.13.5'"
ok "Core dependencies available (uvicorn + aiohttp confirmed)"

# ── 5. Database connectivity + migrations ────────────────────────────────────
echo "[ 5/8 ] Database"
DB_CHECK=$(python3 - <<'PYEOF'
import sys, os
try:
    from sqlalchemy import create_engine, text
    url = os.environ["DATABASE_URL"]
    # Normalise async drivers for sync check
    url = url.replace("postgresql+asyncpg://", "postgresql://") \
             .replace("sqlite+aiosqlite:///", "sqlite:///") \
             .replace("postgres://", "postgresql://", 1)
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5} if "postgresql" in url else {})
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("ok")
except Exception as e:
    print(f"error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
)
if [ "${DB_CHECK}" != "ok" ]; then
    fail "Database connection failed. Check DATABASE_URL."
fi
ok "Database reachable"

if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
    echo "       Running Alembic migrations…"
    python3 -m alembic upgrade head || fail "Alembic migration failed"
    ok "Migrations up to date"
else
    warn "SKIP_MIGRATIONS=true — skipping alembic upgrade"
fi

# ── 6. Redis connectivity ─────────────────────────────────────────────────────
echo "[ 6/8 ] Redis"
REDIS_CHECK=$(python3 - <<'PYEOF'
import sys, os
try:
    import redis as _r
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = _r.from_url(url, socket_connect_timeout=3, socket_timeout=3)
    client.ping()
    print("ok")
except Exception as e:
    print(f"error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
)
if [ "${REDIS_CHECK}" != "ok" ]; then
    fail "Redis connection failed. Check REDIS_URL."
fi
ok "Redis reachable"

# ── 7. Startup validator (Python-level checks) ────────────────────────────────
echo "[ 7/8 ] Startup validator"
python3 - <<'PYEOF'
import sys
try:
    from config.startup_validator import validate_environment
    validate_environment(strict=True)
    print("ok")
except SystemExit as e:
    sys.exit(e.code)
except Exception as e:
    print(f"Startup validator error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
ok "Startup validator passed"

# ── 8. Smoke tests (optional) ─────────────────────────────────────────────────
echo "[ 8/8 ] Smoke tests"
if [ "${SKIP_TESTS:-false}" = "true" ]; then
    warn "SKIP_TESTS=true — skipping pytest"
else
    python3 -m pytest tests/ -q --tb=short \
        -m "not slow and not integration" \
        --timeout=30 \
        --no-header \
        -x \
        2>&1 | tail -5 || fail "Smoke tests failed — fix before deploying"
    ok "Smoke tests passed"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  All pre-flight checks passed. Starting HOPEFX AI Trading…${NC}"
echo ""
