#!/usr/bin/env bash
# scripts/diagnose_deploy.sh
# ==========================
# One command that answers "why is the app container unhealthy?".
#
# The app runs `preflight.sh && python app.py` behind a healthcheck, and every
# other service waits on it via `depends_on: condition: service_healthy`. So a
# failure anywhere — a bad env value, a rejected database password, a blocked
# migration, an OOM kill, a crash during startup — surfaces identically:
#
#     dependency failed to start: container hopefx-ai-trading-app-1 is unhealthy
#
# That one string covers at least a dozen distinct causes, and the evidence that
# separates them is spread across `docker compose ps`, `docker inspect`, the app
# log, the Postgres session table and the host's memory. Collecting it by hand,
# in the right order, under pressure, is where the time goes.
#
# This prints all of it in one pass, compact enough to paste.
#
# Secrets are never printed. Environment checks report names and counts only.
#
# Usage:
#     bash scripts/diagnose_deploy.sh
#     bash scripts/diagnose_deploy.sh > report.txt 2>&1

set -uo pipefail   # deliberately no -e: a failing probe must not stop the report

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVICE="${SERVICE:-app}"
DB_USER="${POSTGRES_USER:-hopefx}"
DB_NAME="${POSTGRES_DB:-hopefx}"

hr() { printf '\n─── %s %s\n' "$1" "$(printf '─%.0s' $(seq 1 $((60 - ${#1}))))"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "HOPEFX deployment diagnosis — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

# ── 1. What is actually running ──────────────────────────────────────────────
hr "1. container state"
if have docker; then
    docker compose ps 2>&1 | head -30
else
    echo "docker not on PATH"
fi

# ── 2. How the app container died, which is the single most useful fact ──────
hr "2. app container exit"
if have docker; then
    CID="$(docker compose ps -q "${SERVICE}" 2>/dev/null | head -1)"
    if [ -n "${CID}" ]; then
        docker inspect "${CID}" \
            --format 'status={{.State.Status}}
exitCode={{.State.ExitCode}}
OOMKilled={{.State.OOMKilled}}
restarts={{.RestartCount}}
startedAt={{.State.StartedAt}}
finishedAt={{.State.FinishedAt}}
health={{if .State.Health}}{{.State.Health.Status}} failing={{.State.Health.FailingStreak}}{{else}}<none>{{end}}' 2>&1
        echo ""
        echo "last healthcheck output:"
        docker inspect "${CID}" \
            --format '{{if .State.Health}}{{range $i, $l := .State.Health.Log}}{{if lt $i 2}}  exit={{$l.ExitCode}} {{$l.Output}}{{end}}{{end}}{{end}}' 2>&1 | head -8
        echo ""
        echo "  OOMKilled=true  -> raise the app memory limit (currently 2G in docker-compose.yml)"
        echo "  exitCode=137    -> killed (OOM or SIGKILL); exitCode=1 -> preflight or app refused to start"
        echo "  exitCode=0 with health=unhealthy -> the app is running but not answering /api/health/live"
    else
        echo "no container for service '${SERVICE}' — it never started; see section 5"
    fi
fi

# ── 3. Where preflight stopped ───────────────────────────────────────────────
hr "3. preflight progress (last attempt)"
if have docker; then
    LOG="$(docker compose logs --no-color --tail 400 "${SERVICE}" 2>/dev/null)"
    if [ -n "${LOG}" ]; then
        LAST_STEP="$(echo "${LOG}" | grep -oE '\[ [0-9]/9 \] [A-Za-z ]+' | tail -1)"
        echo "reached: ${LAST_STEP:-<no preflight output — the container may not have run its command>}"
        echo ""
        echo "checks seen in the last run:"
        echo "${LOG}" | grep -E '\[ [0-9]/9 \]|✓|✗|⚠|FAIL|Error|error:' | tail -25
    else
        echo "no logs for '${SERVICE}'"
    fi
fi

# ── 4. The tail, which carries the actual exception ──────────────────────────
hr "4. app log tail"
if have docker; then
    docker compose logs --no-color --tail 60 "${SERVICE}" 2>&1 | tail -60
fi

# ── 5. Environment sanity — names and counts only, never values ──────────────
hr "5. environment (.env — the file compose injects)"
if [ -f .env ]; then
    echo "present: .env ($(wc -l < .env) lines, mode $(stat -c '%a' .env 2>/dev/null || echo '?'))"
    # grep -c prints 0 AND exits 1 when there are no matches, so `|| echo 0`
    # would emit the count twice. `|| true` keeps grep's own 0.
    PLACEHOLDERS="$(grep -cE '^[A-Z0-9_]+=[[:space:]]*CHANGE_ME' .env 2>/dev/null || true)"
    COMMENTVALS="$(grep -cE '^[A-Z0-9_]+=[[:space:]]+#' .env 2>/dev/null || true)"
    echo "unreplaced CHANGE_ME placeholders : ${PLACEHOLDERS}   (must be 0)"
    echo "values that are really comments   : ${COMMENTVALS}   (must be 0 — see commit 57b2294)"
    [ "${PLACEHOLDERS}" != "0" ] && grep -nE '^[A-Z0-9_]+=[[:space:]]*CHANGE_ME' .env | cut -d= -f1
    [ "${COMMENTVALS}" != "0" ] && grep -nE '^[A-Z0-9_]+=[[:space:]]+#' .env | cut -d= -f1

    echo ""
    echo "required variables (present/absent only):"
    for V in APP_ENV HOPEFX_DOMAIN SECURITY_JWT_SECRET CONFIG_ENCRYPTION_KEY \
             HOPEFX_KILL_SWITCH_TOKEN CRYPTO_WEBHOOK_SECRET DATABASE_URL \
             POSTGRES_PASSWORD DB_PASSWORD REDIS_URL REDIS_PASSWORD \
             GRAFANA_ADMIN_PASSWORD BOOTSTRAP_SUPERADMIN_EMAIL; do
        if grep -qE "^${V}=." .env 2>/dev/null; then echo "  ok      ${V}"; else echo "  MISSING ${V}"; fi
    done

    echo ""
    echo "consistency (the three that must agree):"
    PGPW="$(grep -E '^POSTGRES_PASSWORD=' .env | head -1 | cut -d= -f2-)"
    DBPW="$(grep -E '^DB_PASSWORD=' .env | head -1 | cut -d= -f2-)"
    URLPW="$(grep -E '^DATABASE_URL=' .env | head -1 | sed -nE 's#.*://[^:]+:([^@]+)@.*#\1#p')"
    if [ -n "${PGPW}" ] && [ "${PGPW}" = "${DBPW}" ] && [ "${PGPW}" = "${URLPW}" ]; then
        echo "  ok      POSTGRES_PASSWORD == DB_PASSWORD == password inside DATABASE_URL"
    else
        echo "  MISMATCH between POSTGRES_PASSWORD / DB_PASSWORD / DATABASE_URL"
        echo "          regenerate with: python3 scripts/bootstrap_env.py --domain <domain> --force"
    fi
else
    echo "NO .env FILE."
    echo "docker-compose.yml declares 'env_file: .env' on every service, so without"
    echo "it the containers get nothing. Note that the --env-file FLAG does not"
    echo "substitute for this file. Create it with:"
    echo "    python3 scripts/bootstrap_env.py --domain <your-domain> --force"
fi

# ── 6. Database: reachable, and is anything blocking a migration ─────────────
hr "6. postgres"
if have docker; then
    docker compose exec -T postgres pg_isready -U "${DB_USER}" -d "${DB_NAME}" 2>&1 | head -3
    echo ""
    echo "sessions (a 'Lock' wait_event_type explains a migration that never finishes):"
    docker compose exec -T postgres psql -U "${DB_USER}" -d "${DB_NAME}" -c \
        "SELECT pid, state, wait_event_type, wait_event, left(query, 45) AS query
           FROM pg_stat_activity WHERE datname = current_database();" 2>&1 | head -15
    echo ""
    echo "alembic version (empty = migrations never completed):"
    docker compose exec -T postgres psql -U "${DB_USER}" -d "${DB_NAME}" -tAc \
        "SELECT version_num FROM alembic_version;" 2>&1 | head -3
fi

# ── 7. Host resources — 10 services with ~7.4G of limits on one box ──────────
hr "7. host resources"
free -h 2>/dev/null | head -3 || echo "free unavailable"
echo ""
df -h . 2>/dev/null | head -3
echo ""
if have docker; then
    echo "per-container memory against limit:"
    timeout 15 docker stats --no-stream --format '  {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' 2>&1 | head -14
fi

hr "end"
echo "Paste this whole report. Secrets are not included."
