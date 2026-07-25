#!/usr/bin/env bash
# HOPEFX-AI-TRADING — generate ONLY the production .env (no Docker, no TLS, no containers).
# =============================================================================
# Use this when the repo is already cloned and Docker is already installed, and
# you just need a complete, valid .env with fresh secrets.
#
#   bash deployments/gen_env.sh <domain> [--force]
#
# Example:
#   bash deployments/gen_env.sh hopefx.site
#
# This exists because the equivalent logic pasted as a long one-liner into a
# terminal is fragile: shell function definitions chained with &&, backslash
# line-continuations mangled by paste, and bracketed-paste mode can all silently
# break it so values never get substituted. A committed script has none of those
# failure modes and is testable.
#
# Safe to re-run. Refuses to clobber an existing .env unless --force is given
# (the previous file is always kept as .env.bak.<timestamp>).
# =============================================================================
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DOMAIN="${1:-}"
FORCE="${2:-}"

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[0;33m'; NC='\033[0m'
ok()   { echo -e "${GRN}  ✔${NC} $*"; }
warn() { echo -e "${YEL}  ⚠${NC} $*"; }
die()  { echo -e "${RED}  ✘${NC} $*" >&2; exit 1; }

[ -n "$DOMAIN" ] || die "Usage: bash deployments/gen_env.sh <domain> [--force]"
[ -f .env.production.example ] || die ".env.production.example not found — are you in the repo root?"
command -v openssl >/dev/null 2>&1 || die "openssl not found. Install with: apt-get install -y openssl"

if [ -f .env ]; then
  if [ "$FORCE" = "--force" ]; then
    BAK=".env.bak.$(date +%Y%m%d%H%M%S)"
    mv .env "$BAK"; warn "Existing .env moved to ${BAK}"
  else
    die ".env already exists. Re-run with --force to replace it (the old one is backed up):
      bash deployments/gen_env.sh ${DOMAIN} --force"
  fi
fi

cp .env.production.example .env
chmod 600 .env

# Replace the value of KEY, preserving every other line. Any trailing inline
# comment on that line is intentionally dropped: Docker Compose's env_file
# parser keeps an inline comment as part of the value when the value is empty,
# so leaving them attached to generated secrets risks contaminating them.
env_set() {
  local key="$1" val="$2"
  awk -v k="$key" -v v="$val" '
    BEGIN { FS = "=" }
    {
      if (index($0, "#") == 1) { print; next }          # keep comment lines verbatim
      if ($1 == k)             { print k "=" v; next }  # replace target key
      print
    }
  ' .env > .env.tmp && mv .env.tmp .env
  chmod 600 .env
}

env_get() { grep -E "^${1}=" .env | tail -1 | cut -d= -f2- ; }

# Password satisfying scripts/create_superadmin.py's policy (>=16 chars, upper +
# lower + digit + special). Specials restricted to '-_=+.,' — all accepted by
# that policy and all inert to the shell, so `set -a; source .env` in
# scripts/preflight.sh cannot truncate or expand them.
gen_password() {
  local upper lower digit special rest
  upper=$(LC_ALL=C tr -dc 'A-Z'      < /dev/urandom | head -c3)
  lower=$(LC_ALL=C tr -dc 'a-z'      < /dev/urandom | head -c3)
  digit=$(LC_ALL=C tr -dc '0-9'      < /dev/urandom | head -c3)
  special=$(LC_ALL=C tr -dc '\-_=+.,' < /dev/urandom | head -c3)
  rest=$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c8)
  echo "${upper}${lower}${digit}${special}${rest}" | fold -w1 | shuf | tr -d '\n'
}

# base64 decoding to exactly 32 bytes, urlsafe alphabet. security/key_manager.py
# runs base64.urlsafe_b64decode() then rejects anything under 32 bytes. Note
# `openssl rand -hex 32` and Python's token_urlsafe(32) both FAIL that check.
gen_b64key() { openssl rand -base64 32 | tr '+/' '-_'; }

echo
echo "Generating .env for ${DOMAIN} ..."

env_set HOPEFX_DOMAIN   "$DOMAIN"
env_set ALLOWED_ORIGINS "https://${DOMAIN}"
env_set APP_BASE_URL    "https://${DOMAIN}"

# utils/config.py reads DB_PASSWORD on an alternate path — keep it identical to
# POSTGRES_PASSWORD so both agree on the same database.
_PG="$(openssl rand -hex 24)"
env_set POSTGRES_PASSWORD "$_PG"
env_set DB_PASSWORD       "$_PG"

env_set REDIS_PASSWORD           "$(openssl rand -hex 24)"
env_set GRAFANA_ADMIN_PASSWORD   "$(openssl rand -hex 16)"
env_set HOPEFX_KILL_SWITCH_TOKEN "$(openssl rand -hex 24)"
env_set CRYPTO_WEBHOOK_SECRET    "$(openssl rand -hex 24)"
env_set CONFIG_SALT              "$(openssl rand -hex 16)"   # must be valid hex

env_set HOPEFX_MASTER_KEY     "$(gen_b64key)"
env_set HOPEFX_ENCRYPTION_KEY "$(gen_b64key)"

for v in SECURITY_JWT_SECRET CONFIG_ENCRYPTION_KEY SECRET_KEY JWT_SECRET \
         JWT_SECRET_KEY LICENSE_SECRET WHITELABEL_KEY_HASH_SECRET \
         TRADINGVIEW_WEBHOOK_SECRET; do
  env_set "$v" "$(openssl rand -hex 32)"
done

for v in BOOTSTRAP_SUPERADMIN_PASSWORD BOOTSTRAP_ADMIN_PASSWORD BOOTSTRAP_TRADER_PASSWORD; do
  env_set "$v" "$(gen_password)"
done

# ── Self-check: fail loudly rather than hand back a broken .env ──────────────
echo
echo "Verifying ..."
FAIL=0

TOTAL=$(grep -cE '^[A-Z_][A-Z0-9_]*=' .env || true)
ok "${TOTAL} variables written"

if grep -qE '^[A-Z_]+=.*CHANGE_ME' .env; then
  echo -e "${RED}  ✘ placeholders NOT replaced:${NC}"
  grep -nE '^[A-Z_]+=.*CHANGE_ME' .env | sed 's/=.*/=CHANGE_ME…/' | sed 's/^/      /'
  FAIL=1
else
  ok "no CHANGE_ME placeholders remain"
fi

# A value that begins with '#' means an inline comment leaked in as the value.
if grep -qE '^[A-Z_]+=[[:space:]]*#' .env; then
  echo -e "${RED}  ✘ inline comment leaked into a value:${NC}"
  grep -nE '^[A-Z_]+=[[:space:]]*#' .env | sed 's/^/      /'
  FAIL=1
else
  ok "no comment-contaminated values"
fi

# scripts/preflight.sh does `set -a; source .env; set +a` — prove that is clean.
if ( set -a; . ./.env; set +a ) >/dev/null 2>/tmp/gen_env_src_err; then
  if [ -s /tmp/gen_env_src_err ]; then
    echo -e "${RED}  ✘ 'source .env' produced errors (a value contains a shell metacharacter):${NC}"
    sed 's/^/      /' /tmp/gen_env_src_err; FAIL=1
  else
    ok "'source .env' is clean (scripts/preflight.sh path)"
  fi
else
  echo -e "${RED}  ✘ 'source .env' failed${NC}"; sed 's/^/      /' /tmp/gen_env_src_err; FAIL=1
fi
rm -f /tmp/gen_env_src_err

for v in HOPEFX_MASTER_KEY HOPEFX_ENCRYPTION_KEY; do
  L=${#v}; VAL=$(env_get "$v")
  [ ${#VAL} -eq 44 ] && ok "${v} is 44-char base64 (key_manager accepts)" \
    || { echo -e "${RED}  ✘ ${v} wrong length: ${#VAL} (expected 44)${NC}"; FAIL=1; }
done

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  if docker compose config --quiet >/dev/null 2>&1; then
    ok "docker compose config resolves cleanly"
  else
    warn "docker compose config reported a problem:"
    docker compose config --quiet 2>&1 | sed 's/^/      /' | head -5
  fi
fi

echo
if [ "$FAIL" -ne 0 ]; then
  die "The generated .env has problems (listed above). Nothing was started."
fi

echo "=============================================================="
ok ".env generated successfully — mode $(stat -c '%a' .env 2>/dev/null || echo 600)"
echo "=============================================================="
echo
echo "  SAVE THESE LOGINS NOW — they are only in .env:"
echo "    superadmin@hopefx.io   $(env_get BOOTSTRAP_SUPERADMIN_PASSWORD)"
echo "    admin@hopefx.io        $(env_get BOOTSTRAP_ADMIN_PASSWORD)"
echo "    trader@hopefx.io       $(env_get BOOTSTRAP_TRADER_PASSWORD)"
echo
echo "  Optional — the AI assistant returns stub answers until you set a key:"
echo "    edit .env and set ANTHROPIC_API_KEY=...  (or LLM_BACKEND=openai + OPENAI_API_KEY=...)"
echo
echo "  Next:  docker compose up -d --build  &&  docker compose ps"
echo
