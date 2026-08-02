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
echo "[ 1/9 ] Python version"
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "${PY_MAJOR}" -lt 3 ] || { [ "${PY_MAJOR}" -eq 3 ] && [ "${PY_MINOR}" -lt 12 ]; }; then
    fail "Python 3.12+ required (found $(python3 --version)). The Docker image uses python:3.12-slim."
fi
ok "Python $(python3 --version | cut -d' ' -f2)"

# ── 2. .env file ──────────────────────────────────────────────────────────────
# docker-compose.yml's `env_file: .env` injects the HOST's .env as process
# environment variables at container-start time — it does NOT copy or mount
# the .env FILE itself into the container filesystem (correctly: a plaintext
# secrets file has no business sitting inside a running container image/fs).
# So inside a container, .env never exists on disk even though every var it
# defines is already present in the environment. Treat "no file, but the
# vars we actually need are already set" as success, not failure — step 3
# below is what actually verifies every required var is present; this step
# only needs to source a file for non-container/manual runs where nothing
# has injected the vars yet.
echo "[ 2/9 ] Environment file"
if [ ! -f ".env" ]; then
    if [ -n "${SECURITY_JWT_SECRET:-}" ] && [ -n "${DATABASE_URL:-}" ]; then
        ok "No .env file, but required vars already present in the environment (container env_file injection)"
    elif [ "${APP_ENV:-development}" = "production" ]; then
        fail ".env not found and required env vars are not set. Copy .env.example and fill in all values, or verify docker-compose's env_file injection."
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
echo "[ 3/9 ] Required environment variables"
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
echo "[ 4/9 ] Python dependencies"
if ! python3 -c "import fastapi, sqlalchemy, alembic, uvicorn, redis, jwt, aiohttp" 2>/dev/null; then
    warn "Some dependencies missing — installing from requirements.txt"
    pip install -r requirements.txt --quiet || fail "pip install failed"
fi
# Hard-fail if uvicorn or aiohttp are still missing after install attempt
python3 -c "import uvicorn" 2>/dev/null || fail "uvicorn not installed — run: pip install 'uvicorn[standard]>=0.27.0'"
python3 -c "import aiohttp" 2>/dev/null || fail "aiohttp not installed — run: pip install 'aiohttp>=3.13.5'"
ok "Core dependencies available (uvicorn + aiohttp confirmed)"

# ── 5. Database connectivity + migrations ────────────────────────────────────
echo "[ 5/9 ] Database"
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
echo "[ 6/9 ] Redis"
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
    # Redis is OPTIONAL: the app degrades gracefully to an in-memory / ring-buffer
    # fallback when Redis is unavailable. A failed check must NOT crash-loop the
    # container (previously `fail` → exit 1). Warn instead and continue.
    # For full multi-process functionality set REDIS_URL to the compose service,
    # e.g. REDIS_URL=redis://redis:6379/0 (host 'redis', NOT 'localhost').
    warn "Redis not reachable — continuing with in-memory fallback. Set REDIS_URL to redis://redis:6379/0 for full functionality."
else
    ok "Redis reachable"
fi

# ── 7. Startup validator (Python-level checks) ────────────────────────────────
echo "[ 7/9 ] Startup validator"
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

# ── 8. Frontend build ─────────────────────────────────────────────────────────
# core/page_routes.py mounts the SPA from ./static, and falls back SILENTLY to
# the committed legacy dashboard/dist (GodMode) and then to a "Build Required"
# placeholder when static/index.html is absent. That silence is the problem: a
# deploy whose frontend-builder stage never ran looks completely healthy — the
# container is up, /api/* works, the health endpoint is green — while the public
# site serves a different application entirely. That is exactly what happened on
# the production VPS, where a stripped single-stage Dockerfile (no
# `COPY --from=frontend-builder /build/static ./static`) shipped for days.
#
# Warn, do not fail: an API-only deployment is legitimate, and refusing to boot
# over a missing UI would be a worse failure than serving one. The point is that
# it can never again be silent.
echo "[ 8/9 ] Frontend build"
if [ -f "static/index.html" ]; then
    if ls static/assets/LandingPage-*.js >/dev/null 2>&1; then
        ok "React SPA present ($(ls static/assets 2>/dev/null | wc -l) assets)"
    else
        warn "static/index.html exists but no LandingPage chunk — build may be partial or stale"
    fi
elif [ -f "dashboard/dist/index.html" ]; then
    warn "static/ is MISSING — the site will serve the LEGACY GodMode dashboard, not the real landing page."
    warn "  The image was built without the frontend-builder stage. Check that Dockerfile"
    warn "  still has: COPY --from=frontend-builder /build/static ./static   (expected size 3506 bytes)"
    warn "  Diagnose from the host with: bash deployments/diagnose_served_page.sh"
else
    warn "No frontend build found — / will serve the 'Build Required' placeholder. API is unaffected."
fi

# ── 9. Smoke tests (optional) ─────────────────────────────────────────────────
echo "[ 9/9 ] Smoke tests"
if [ "${SKIP_TESTS:-false}" = "true" ]; then
    warn "SKIP_TESTS=true — skipping pytest"
elif ! python3 -c "import pytest, pytest_asyncio, pytest_timeout" >/dev/null 2>&1; then
    # pytest, pytest-asyncio and pytest-timeout are declared in
    # requirements-ci.txt / requirements-dev.txt only — the production image
    # installs requirements.txt, so the test toolchain is deliberately absent.
    #
    # This step used to run pytest regardless. tests/fixtures/db.py imports
    # pytest_asyncio at module scope as a registered plugin, so collection
    # aborted before a single test ran, `fail` exited 1, and because the
    # container runs `preflight.sh && python app.py` the `&&` short-circuited
    # and the app never started. A test toolchain that is absent by design is
    # a property of the image, not a reason to refuse to boot.
    warn "test toolchain not installed — skipping smoke tests (expected in the production image)"
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
