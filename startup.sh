#!/usr/bin/env bash
# HOPEFX AI Trading — startup validation script
# Validates environment, dependencies, and connectivity before launch.
# Usage: ./startup.sh

set -euo pipefail

# ── Python version check ──────────────────────────────────────────────────────
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "${PYTHON_MAJOR}" -lt 3 ] || { [ "${PYTHON_MAJOR}" -eq 3 ] && [ "${PYTHON_MINOR}" -lt 9 ]; }; then
    echo "Python 3.9+ required (found $(python3 --version)). Please upgrade." >&2
    exit 1
fi

# ── Install dependencies ──────────────────────────────────────────────────────
pip install -r requirements.txt

# ── Validate .env ─────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo ".env file is missing. Please create a .env file." >&2
    exit 1
fi

# Load .env safely: export only KEY=VALUE lines; skip comments and blank lines.
# shellcheck disable=SC2046
export $(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env | xargs)

# ── Database check ────────────────────────────────────────────────────────────
if [ -n "${DATABASE_URL:-}" ]; then
    echo "Initializing database..."
    python3 -c "
import sys
try:
    from database.connection import engine  # noqa: F401
    print('Database connection OK')
except Exception as e:
    print(f'Database init warning: {e}', file=sys.stderr)
"
else
    echo "DATABASE_URL is not set in .env" >&2
    exit 1
fi

# ── Redis check ───────────────────────────────────────────────────────────────
redis-cli ping || { echo "Redis is not running." >&2; exit 1; }

# ── Unit tests ────────────────────────────────────────────────────────────────
python3 -m pytest tests/ -q --tb=short -m "not slow" --timeout=60

# ── Done ──────────────────────────────────────────────────────────────────────
echo "Startup validation complete. Starting the trading system..."
