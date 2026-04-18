#!/usr/bin/env bash
# scripts/stamp_db.sh
# Stamp the alembic_version table to the current head revision.
#
# Use this when the database schema was created outside of Alembic (e.g. via
# database_init.py or SQLAlchemy create_all) and you need to bring the
# migration history in sync without re-running all migrations.
#
# Usage:
#   ./scripts/stamp_db.sh                  # stamp to head (default)
#   ./scripts/stamp_db.sh c1d2e3f4a5b6     # stamp to a specific revision
#
# The script runs `alembic upgrade head` first so any pending migrations are
# applied, then stamps the version.  On a fresh DB this is equivalent to a
# full migration run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

TARGET="${1:-head}"

echo "[stamp_db] Running alembic upgrade ${TARGET}…"
python3 -m alembic upgrade "${TARGET}"

echo "[stamp_db] Stamping alembic_version to ${TARGET}…"
python3 -m alembic stamp "${TARGET}"

echo "[stamp_db] Current revision:"
python3 -m alembic current

echo "[stamp_db] Done — DB is fully in sync with migration head."
