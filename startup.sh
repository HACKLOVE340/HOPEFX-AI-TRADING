#!/usr/bin/env bash
# startup.sh — delegates to scripts/preflight.sh then starts the API server.
#
# Usage:
#   ./startup.sh                        # full pre-flight + start
#   SKIP_TESTS=true ./startup.sh        # skip pytest (faster restarts)
#   SKIP_MIGRATIONS=true ./startup.sh   # skip alembic upgrade

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

bash scripts/preflight.sh

echo "Starting HOPEFX AI Trading API server…"
exec python app.py
