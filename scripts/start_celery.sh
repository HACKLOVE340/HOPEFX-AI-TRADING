#!/usr/bin/env bash
# scripts/start_celery.sh
# Start Celery worker and/or beat scheduler for HOPEFX AI Trading.
#
# Usage:
#   ./scripts/start_celery.sh worker          # worker only (default)
#   ./scripts/start_celery.sh beat            # beat scheduler only
#   ./scripts/start_celery.sh worker+beat     # combined (dev only — single process)
#   ./scripts/start_celery.sh flower          # Flower monitoring UI on :5555
#
# Environment variables (override via .env or shell):
#   CELERY_BROKER_URL      — Redis broker  (default: redis://localhost:6379/1)
#   CELERY_RESULT_BACKEND  — Redis backend (default: redis://localhost:6379/2)
#   CELERY_CONCURRENCY     — Worker threads (default: 4)
#   CELERY_LOGLEVEL        — Log level      (default: info)
#   CELERY_QUEUES          — Comma-separated queues (default: ml,billing,risk,infra,celery)
#   FLOWER_PORT            — Flower UI port (default: 5555)
#   FLOWER_BASIC_AUTH      — user:password for Flower basic auth (optional)

set -euo pipefail

# ── Load .env if present ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
    # Export only lines that are KEY=VALUE (skip comments and blank lines)
    set -a
    # shellcheck disable=SC1090
    source <(grep -E '^[A-Z_][A-Z0-9_]*=' "$ENV_FILE" | grep -v '^#')
    set +a
fi

# ── Defaults ──────────────────────────────────────────────────────────────────
CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://localhost:6379/1}"
CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://localhost:6379/2}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-4}"
CELERY_LOGLEVEL="${CELERY_LOGLEVEL:-info}"
CELERY_QUEUES="${CELERY_QUEUES:-ml,billing,risk,infra,celery}"
FLOWER_PORT="${FLOWER_PORT:-5555}"
FLOWER_BASIC_AUTH="${FLOWER_BASIC_AUTH:-}"

export CELERY_BROKER_URL CELERY_RESULT_BACKEND

MODE="${1:-worker}"

cd "$PROJECT_ROOT"

# ── Verify Celery is installed ────────────────────────────────────────────────
if ! python -c "import celery" 2>/dev/null; then
    echo "ERROR: celery is not installed."
    echo "Install with: pip install 'celery[redis]>=5.4.0'"
    exit 1
fi

# ── Verify broker is reachable ────────────────────────────────────────────────
echo "Checking broker connectivity: $CELERY_BROKER_URL"
if ! python -c "
import redis, os, urllib.parse
url = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/1')
parsed = urllib.parse.urlparse(url)
host = parsed.hostname or 'localhost'
port = parsed.port or 6379
password = parsed.password or None
db = int(parsed.path.lstrip('/') or '1')
r = redis.Redis(host=host, port=port, password=password, db=db, socket_connect_timeout=5)
r.ping()
print('Broker OK')
" 2>/dev/null; then
    echo "WARNING: Could not reach broker at $CELERY_BROKER_URL — worker may fail to start."
    echo "Ensure Redis is running and CELERY_BROKER_URL is correct."
fi

# ── Launch ────────────────────────────────────────────────────────────────────
case "$MODE" in
    worker)
        echo "Starting Celery worker (concurrency=$CELERY_CONCURRENCY, queues=$CELERY_QUEUES)"
        exec celery -A celery_app worker \
            --loglevel="$CELERY_LOGLEVEL" \
            --concurrency="$CELERY_CONCURRENCY" \
            --queues="$CELERY_QUEUES" \
            --hostname="worker@%h"
        ;;

    beat)
        echo "Starting Celery Beat scheduler"
        # PersistentScheduler stores the schedule in a shelve file so tasks
        # are not re-fired immediately after a restart.
        BEAT_SCHEDULE_DIR="${PROJECT_ROOT}/state"
        mkdir -p "$BEAT_SCHEDULE_DIR"
        exec celery -A celery_app beat \
            --loglevel="$CELERY_LOGLEVEL" \
            --scheduler=celery.beat:PersistentScheduler \
            --schedule="${BEAT_SCHEDULE_DIR}/celerybeat-schedule"
        ;;

    worker+beat)
        echo "Starting Celery worker + beat (dev mode — single process)"
        echo "WARNING: Do not use worker+beat in production. Run separate worker and beat services."
        BEAT_SCHEDULE_DIR="${PROJECT_ROOT}/state"
        mkdir -p "$BEAT_SCHEDULE_DIR"
        exec celery -A celery_app worker \
            --beat \
            --loglevel="$CELERY_LOGLEVEL" \
            --concurrency="$CELERY_CONCURRENCY" \
            --queues="$CELERY_QUEUES" \
            --hostname="worker@%h" \
            --schedule="${BEAT_SCHEDULE_DIR}/celerybeat-schedule"
        ;;

    flower)
        echo "Starting Flower monitoring UI on port $FLOWER_PORT"
        if ! python -c "import flower" 2>/dev/null; then
            echo "ERROR: flower is not installed."
            echo "Install with: pip install flower"
            exit 1
        fi
        FLOWER_ARGS=(
            -A celery_app flower
            --port="$FLOWER_PORT"
            --broker="$CELERY_BROKER_URL"
            --loglevel="$CELERY_LOGLEVEL"
        )
        if [[ -n "$FLOWER_BASIC_AUTH" ]]; then
            FLOWER_ARGS+=(--basic_auth="$FLOWER_BASIC_AUTH")
        fi
        exec celery "${FLOWER_ARGS[@]}"
        ;;

    *)
        echo "Unknown mode: $MODE"
        echo "Usage: $0 [worker|beat|worker+beat|flower]"
        exit 1
        ;;
esac
