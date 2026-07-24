#!/usr/bin/env bash
# HOPEFX-AI-TRADING — clean VPS redeploy (app-level, NOT a machine wipe)
# =============================================================================
# Wipes the app to a clean slate — fresh code, fresh DB/Redis volumes, fresh
# build — WITHOUT touching the OS, Docker, TLS certs, or DNS. Your .env is
# preserved (it holds your secrets).
#
#   bash deployments/vps_reset.sh          # interactive (asks to confirm)
#   bash deployments/vps_reset.sh --yes    # non-interactive (CI)
#
# It VALIDATES .env before destroying anything, so you never wipe data and then
# discover the app can't start.
# =============================================================================
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[0;33m'; NC='\033[0m'
say()  { echo -e "$*"; }
ok()   { echo -e "${GRN}✔${NC} $*"; }
warn() { echo -e "${YEL}⚠${NC} $*"; }
die()  { echo -e "${RED}x${NC} $*" >&2; exit 1; }

ASSUME_YES=0
[ "${1:-}" = "--yes" ] || [ "${1:-}" = "-y" ] && ASSUME_YES=1

# ── 0. Sanity ─────────────────────────────────────────────────────────────────
[ -f docker-compose.yml ] || die "Run this from the repo root (docker-compose.yml not found)."
[ -f .env ] || die ".env is missing — create it first (cp .env.production.example .env && nano .env). Refusing to wipe without it."

# Resolve compose command
if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE=(docker-compose)
else die "Docker Compose not installed."; fi

# ── 1. Validate required .env values BEFORE any destruction ──────────────────
getenv() { grep -E "^${1}=" .env | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" ; }

REQUIRED=(APP_ENV HOPEFX_DOMAIN ALLOWED_ORIGINS POSTGRES_PASSWORD REDIS_PASSWORD
          CONFIG_ENCRYPTION_KEY HOPEFX_KILL_SWITCH_TOKEN CRYPTO_WEBHOOK_SECRET)
missing=()
for v in "${REQUIRED[@]}"; do
  val="$(getenv "$v" || true)"
  if [ -z "$val" ] || echo "$val" | grep -qi "CHANGE_ME"; then missing+=("$v"); fi
done
# JWT secret: accept either canonical name
jwt="$(getenv SECURITY_JWT_SECRET || true)"; [ -n "$jwt" ] || jwt="$(getenv JWT_SECRET_KEY || true)"
{ [ -z "$jwt" ] || echo "$jwt" | grep -qi "CHANGE_ME"; } && missing+=("SECURITY_JWT_SECRET")
[ -n "$jwt" ] && [ "${#jwt}" -lt 32 ] && missing+=("SECURITY_JWT_SECRET(too_short:need>=32)")

if [ "${#missing[@]}" -gt 0 ]; then
  echo
  die "These required .env values are missing or still 'CHANGE_ME':\n  - ${missing[*]}\nFill them in .env (openssl rand -hex 32 for secrets), then re-run."
fi
ok "All required .env values present."

# LLM key (warn only)
if [ -z "$(getenv ANTHROPIC_API_KEY || true)" ] && [ -z "$(getenv OPENAI_API_KEY || true)" ]; then
  warn "No ANTHROPIC_API_KEY or OPENAI_API_KEY set — the AI assistant won't work until you add one."
fi

# ── 2. Confirm the destructive wipe ──────────────────────────────────────────
DOMAIN="$(getenv HOPEFX_DOMAIN)"
echo
warn "This will DESTROY all app data volumes (Postgres, Redis, state) and rebuild from origin/main."
warn "Preserved: .env, TLS certs (/etc/letsencrypt), DNS, Docker itself.  Domain: ${DOMAIN}"
if [ "$ASSUME_YES" -ne 1 ]; then
  read -r -p "Type WIPE to continue: " ans
  [ "$ans" = "WIPE" ] || die "Aborted (you did not type WIPE)."
fi

# ── 3. Tear down containers + volumes ────────────────────────────────────────
say "\n[1/6] Stopping containers and removing data volumes..."
"${COMPOSE[@]}" down -v --remove-orphans || true
ok "Down."

# ── 4. Reset code to origin/main ─────────────────────────────────────────────
say "\n[2/6] Resetting code to origin/main..."
git fetch origin --prune
git reset --hard origin/main
ok "Code at $(git rev-parse --short HEAD)."

# ── 5. Reclaim disk ──────────────────────────────────────────────────────────
say "\n[3/6] Pruning old images / build cache..."
docker system prune -af >/dev/null 2>&1 || true
ok "Pruned."

# ── 6. Rebuild + start ───────────────────────────────────────────────────────
say "\n[4/6] Building and starting the stack (first build can take a few minutes)..."
"${COMPOSE[@]}" up -d --build --remove-orphans
ok "Started."

# ── 7. Wait for app health ───────────────────────────────────────────────────
say "\n[5/6] Waiting for the app to become healthy..."
healthy=0
for i in $(seq 1 40); do
  if "${COMPOSE[@]}" exec -T app curl -fsS http://localhost:8000/api/health/live >/dev/null 2>&1; then
    healthy=1; ok "App healthy after ${i} checks."; break
  fi
  sleep 3
done
if [ "$healthy" -ne 1 ]; then
  warn "App not healthy yet. Recent logs:"
  "${COMPOSE[@]}" logs --tail=60 app || true
fi

# ── 8. Seed the superadmin (best-effort) ─────────────────────────────────────
say "\n[6/6] Creating the superadmin account on the fresh database..."
"${COMPOSE[@]}" exec -T app python scripts/create_superadmin.py || \
  warn "Could not auto-create superadmin — run manually: ${COMPOSE[*]} exec app python scripts/create_superadmin.py"

echo
"${COMPOSE[@]}" ps
echo
ok "Clean redeploy complete. Open https://${DOMAIN} and check the live landing."
[ "$healthy" -eq 1 ] || warn "If the app is still restarting, paste the logs above and the platform_doctor output."
