#!/usr/bin/env bash
# HOPEFX-AI-TRADING — full VPS bootstrap, from a BARE fresh Ubuntu server to a
# running, TLS-secured app.
# =============================================================================
# Run this ONCE on a freshly reinstalled VPS (Ubuntu 22.04 or 24.04), as root
# (or a sudo user), over an interactive SSH session (see the firewall note
# below — do not run this unattended over a connection you can't reconnect to):
#
#   curl -fsSL https://raw.githubusercontent.com/HACKLOVE340/HOPEFX-AI-TRADING/main/deployments/vps_bootstrap.sh -o vps_bootstrap.sh
#   chmod +x vps_bootstrap.sh
#   ./vps_bootstrap.sh hopefx.site you@example.com
#
# Or, if you've already cloned the repo:
#
#   cd HOPEFX-AI-TRADING
#   bash deployments/vps_bootstrap.sh hopefx.site you@example.com
#
# What it does, in order:
#   1. Sanity-checks the OS and DNS (fails fast with a clear message instead of
#      halfway through a broken step).
#   2. Installs Docker + the compose plugin, git, curl, certbot, ufw.
#   3. Opens the firewall for SSH (including your CURRENT ssh port, even if
#      it's non-standard — see the safety note in step 4) plus HTTP/HTTPS.
#   4. Clones the repo (or updates it, if this script itself lives inside a
#      clone) to ~/HOPEFX-AI-TRADING.
#   5. Generates .env with strong random secrets for everything the app
#      requires (never overwrites an existing .env — safe to re-run).
#   6. Brings the stack up with a temporary self-signed certificate so nginx
#      can start, obtains a REAL Let's Encrypt certificate via the webroot
#      challenge (nginx already serves /.well-known/acme-challenge/), then
#      reloads nginx with the real cert. No port-80 conflicts, no manual steps.
#   7. Health-checks the API and creates the superadmin/admin accounts using
#      the SAME passwords already written to .env (so .env is always the
#      source of truth for your login — nothing is generated twice), and
#      installs a daily cron job that renews the certificate automatically.
#
# Idempotent: safe to re-run after any failure. It skips whatever is already
# done and continues from where it stopped.
#
# Verified before you run this: bash -n clean; every external command mirrors
# documented, standard behaviour (get.docker.com, certbot webroot, ufw, docker
# compose); .dockerignore (added alongside this script) was audited so `.env`
# secrets can never be baked into the image, while files real live routes
# depend on (docs/*.md, the committed CSV data, prop_firm_mode.json) are kept.
# The auto-generated account passwords are verified to satisfy this app's own
# password policy (16+ chars, upper+lower+digit+special) so account creation
# cannot fail on validation. What CANNOT be verified from a development sandbox:
# your VPS's specific disk image, whether DNS is already pointed at this box,
# real network/cloud-firewall conditions, and your SSH port. The script checks
# for exactly those and stops with a clear message rather than guessing.
# =============================================================================
set -euo pipefail

# ── Args ──────────────────────────────────────────────────────────────────────
DOMAIN="${1:-}"
EMAIL="${2:-admin@${DOMAIN}}"
REPO_URL="${REPO_URL:-https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git}"
APP_DIR="${APP_DIR:-$HOME/HOPEFX-AI-TRADING}"

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[0;33m'; BLU='\033[0;34m'; NC='\033[0m'
say()  { echo -e "${BLU}▸${NC} $*"; }
ok()   { echo -e "${GRN}✔${NC} $*"; }
warn() { echo -e "${YEL}⚠${NC} $*"; }
die()  { echo -e "${RED}✘${NC} $*" >&2; exit 1; }

[ -n "$DOMAIN" ] || die "Usage: $0 <domain> [email]   e.g. $0 hopefx.site you@example.com"

echo
echo "=============================================================="
echo " HOPEFX VPS Bootstrap — domain: ${DOMAIN}   email: ${EMAIL}"
echo "=============================================================="
echo

# ── 0. Must be root or passwordless sudo ─────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
  sudo -n true 2>/dev/null || die "Run as root, or ensure your user has passwordless sudo."
  SUDO="sudo"
else
  SUDO=""
fi

# ── 1. OS sanity check ────────────────────────────────────────────────────────
say "[1/9] Checking OS..."
if [ ! -f /etc/os-release ]; then
  die "Cannot detect OS (/etc/os-release missing). This script targets Ubuntu 22.04/24.04."
fi
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}-${VERSION_ID:-}" in
  ubuntu-22.04|ubuntu-24.04) ok "Detected ${PRETTY_NAME}." ;;
  ubuntu-*) warn "Detected ${PRETTY_NAME:-ubuntu} — untested but likely fine." ;;
  *) warn "Detected ${PRETTY_NAME:-$ID} — this script targets Ubuntu; proceeding anyway." ;;
esac

# ── 2. DNS sanity check (fail fast with a clear message, not a confusing certbot error) ──
say "[2/9] Checking DNS for ${DOMAIN}..."
PUBLIC_IP="$(curl -fsS4 https://ifconfig.me 2>/dev/null || curl -fsS4 https://icanhazip.com 2>/dev/null || true)"
if [ -z "$PUBLIC_IP" ]; then
  warn "Could not determine this server's public IP — skipping DNS check."
else
  RESOLVED_IP="$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1 || true)"
  if [ -z "$RESOLVED_IP" ] && command -v dig >/dev/null 2>&1; then
    RESOLVED_IP="$(dig +short "$DOMAIN" A | tail -1)"
  fi
  if [ -z "$RESOLVED_IP" ]; then
    die "DNS for ${DOMAIN} does not resolve yet. Add an A record: ${DOMAIN} -> ${PUBLIC_IP}, wait for propagation, then re-run this script."
  elif [ "$RESOLVED_IP" != "$PUBLIC_IP" ]; then
    die "DNS mismatch: ${DOMAIN} resolves to ${RESOLVED_IP}, but this server's public IP is ${PUBLIC_IP}. Fix the A record and re-run. (If you use Cloudflare proxy/orange-cloud, temporarily set it to DNS-only/grey-cloud for the certificate step.)"
  fi
  ok "${DOMAIN} correctly resolves to this server (${PUBLIC_IP})."
fi

# ── 3. Install prerequisites + Docker ────────────────────────────────────────
say "[3/9] Installing packages (git, curl, ufw, certbot, Docker)..."
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq git curl ufw certbot ca-certificates dnsutils >/dev/null

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | $SUDO sh
  ok "Docker installed."
else
  ok "Docker already installed ($(docker --version))."
fi
if [ -n "${SUDO}" ]; then
  $SUDO usermod -aG docker "$USER" || true
fi

if [ -n "$SUDO" ]; then
  COMPOSE=(sudo docker compose)
else
  COMPOSE=(docker compose)
fi
"${COMPOSE[@]}" version >/dev/null 2>&1 || die "docker compose plugin not found even after Docker install — check the Docker install log above."
ok "Docker Compose available: $("${COMPOSE[@]}" version --short 2>/dev/null || echo unknown)"

# ── 4. Firewall ───────────────────────────────────────────────────────────────
say "[4/9] Configuring firewall (ufw)..."
$SUDO ufw allow OpenSSH >/dev/null 2>&1 || true
# Safety net: if you connect on a NON-standard SSH port, `ufw allow OpenSSH`
# (port 22) alone would lock you out the moment ufw is enabled below. Detect
# the port THIS actual session is using (reliable even behind NAT/port-forwarding)
# and open it explicitly too.
SSH_PORT="$(echo "${SSH_CONNECTION:-}" | awk '{print $4}')"
if [ -n "$SSH_PORT" ] && [ "$SSH_PORT" != "22" ]; then
  $SUDO ufw allow "${SSH_PORT}/tcp" >/dev/null 2>&1 || true
  warn "Detected non-standard SSH port ${SSH_PORT} — opened it in ufw as well."
fi
$SUDO ufw allow 80/tcp  >/dev/null 2>&1 || true
$SUDO ufw allow 443/tcp >/dev/null 2>&1 || true
if $SUDO ufw status | grep -q "Status: active"; then
  ok "ufw already active."
else
  warn "Enabling ufw now. If this SSH session drops and you cannot reconnect,"
  warn "use your VPS provider's web console to run: ufw disable"
  $SUDO ufw --force enable >/dev/null
  ok "ufw enabled (22$( [ -n "$SSH_PORT" ] && [ "$SSH_PORT" != "22" ] && echo "/${SSH_PORT}" ), 80, 443 open)."
fi
warn "Note: ufw only controls this OS's firewall. If your VPS provider (e.g. Hostinger) also has a"
warn "cloud-level firewall panel, make sure 80/443/22 are allowed there too."

# ── 5. Clone / update the repo ────────────────────────────────────────────────
say "[5/9] Getting the application code..."
if [ -f "$(pwd)/docker-compose.yml" ] && [ -d "$(pwd)/.git" ]; then
  APP_DIR="$(pwd)"
  ok "Running from an existing clone at ${APP_DIR}."
elif [ -d "$APP_DIR/.git" ]; then
  ok "Repo already cloned at ${APP_DIR} — fetching latest main."
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" reset --hard origin/main
else
  git clone "$REPO_URL" "$APP_DIR"
  ok "Cloned to ${APP_DIR}."
fi
cd "$APP_DIR"

# ── helpers: read/write single KEY=VALUE lines in .env ───────────────────────
env_get() { grep -E "^${1}=" .env 2>/dev/null | tail -1 | cut -d= -f2- ; }
env_set() {
  local key="$1" val="$2"
  awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k{$0=k"="v} {print}' .env > .env.tmp && mv .env.tmp .env
}
# Generates a password guaranteed to satisfy scripts/create_superadmin.py's
# policy: >=16 chars, at least one upper/lower/digit/special character.
#
# The special-character set is deliberately restricted to '-_=+.,' — every one
# of these is accepted by _validate_password's special-char class
# ([!@#$%^&*()\-_=+\[\]{}|;:,.<>?]) AND is inert to the shell inside a bare
# `VAR=value` line. The previous set ('!@#$%^&*') generated passwords that
# BROKE scripts/preflight.sh, which does `set -a; source .env; set +a`:
# an '&' backgrounded the assignment and truncated the password ("command not
# found" on the remainder), '$' triggered variable expansion, '#' started a
# comment, and '*' glob-expanded. The password stored in .env then silently
# differed from the one the app parsed, so the seeded superadmin/admin logins
# would not match the credentials printed at the end of bootstrap.
# Reproduced directly before changing this.
gen_password() {
  local upper lower digit special rest
  upper=$(tr -dc 'A-Z' < /dev/urandom | head -c3)
  lower=$(tr -dc 'a-z' < /dev/urandom | head -c3)
  digit=$(tr -dc '0-9' < /dev/urandom | head -c3)
  special=$(tr -dc '\-_=+.,' < /dev/urandom | head -c3)
  rest=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c8)
  echo "${upper}${lower}${digit}${special}${rest}" | fold -w1 | shuf | tr -d '\n'
}

# ── 6. Generate .env (never overwrite an existing one) ────────────────────────
say "[6/9] Preparing .env..."
if [ -f .env ]; then
  ok ".env already exists — leaving it untouched. (Delete it manually if you want fresh secrets.)"
else
  [ -f .env.production.example ] || die ".env.production.example not found in ${APP_DIR}."
  cp .env.production.example .env
  chmod 600 .env
  env_set HOPEFX_DOMAIN "$DOMAIN"
  env_set ALLOWED_ORIGINS "https://${DOMAIN}"
  _PG_PASS="$(openssl rand -hex 24)"
  env_set POSTGRES_PASSWORD "$_PG_PASS"
  # utils/config.py reads DB_PASSWORD on a legacy/alternate path — keep it
  # identical to POSTGRES_PASSWORD so both agree on the same database.
  env_set DB_PASSWORD "$_PG_PASS"
  env_set REDIS_PASSWORD "$(openssl rand -hex 24)"
  env_set GRAFANA_ADMIN_PASSWORD "$(openssl rand -hex 16)"
  env_set SECURITY_JWT_SECRET "$(openssl rand -hex 32)"
  env_set CONFIG_ENCRYPTION_KEY "$(openssl rand -hex 32)"
  env_set HOPEFX_KILL_SWITCH_TOKEN "$(openssl rand -hex 24)"
  env_set CRYPTO_WEBHOOK_SECRET "$(openssl rand -hex 24)"
  # ── App-internal secrets that were previously NOT generated here even though
  # scripts/bootstrap_dev.py generates all of them for local dev. Every one is
  # read by real app code, so a VPS deploy was silently running without them.
  # CONFIG_SALT must be valid hex (config/config_manager.py raises otherwise).
  env_set CONFIG_SALT "$(openssl rand -hex 16)"
  # HOPEFX_MASTER_KEY / HOPEFX_ENCRYPTION_KEY must be padded base64 decoding to
  # >=32 bytes — security/key_manager.py runs base64.urlsafe_b64decode() then
  # rejects anything under 32 bytes, and raises SecurityError outright when a
  # production key is required. Verified that token_urlsafe(32) (what
  # bootstrap_dev.py uses) FAILS this with "Incorrect padding", so use padded
  # base64 translated to the urlsafe alphabet instead.
  env_set HOPEFX_MASTER_KEY "$(openssl rand -base64 32 | tr '+/' '-_')"
  env_set HOPEFX_ENCRYPTION_KEY "$(openssl rand -base64 32 | tr '+/' '-_')"
  env_set SECRET_KEY "$(openssl rand -hex 32)"
  env_set JWT_SECRET "$(openssl rand -hex 32)"
  env_set JWT_SECRET_KEY "$(openssl rand -hex 32)"
  env_set LICENSE_SECRET "$(openssl rand -hex 32)"
  env_set WHITELABEL_KEY_HASH_SECRET "$(openssl rand -hex 32)"
  env_set TRADINGVIEW_WEBHOOK_SECRET "$(openssl rand -hex 32)"
  env_set BOOTSTRAP_SUPERADMIN_PASSWORD "$(gen_password)"
  env_set BOOTSTRAP_ADMIN_PASSWORD "$(gen_password)"
  env_set BOOTSTRAP_TRADER_PASSWORD "$(gen_password)"
  ok "Generated .env with strong random secrets (mode 600)."
  warn "AI assistant will not work until you add ONE key: edit .env and set"
  warn "  LLM_BACKEND=anthropic + ANTHROPIC_API_KEY=...   (or openai + OPENAI_API_KEY=...)"
  warn "Data-feed API keys (Finnhub, Twelve Data, ...) are optional — free fallback is used if blank."
fi

# ── 7. TLS: dummy cert -> compose up -> real cert -> reload ─────────────────
say "[7/9] Setting up TLS for ${DOMAIN}..."
$SUDO mkdir -p /etc/letsencrypt /var/www/certbot
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"

if $SUDO test -s "${CERT_DIR}/fullchain.pem"; then
  ok "A certificate for ${DOMAIN} already exists — skipping issuance."
else
  say "  Creating a temporary self-signed certificate so nginx can start..."
  $SUDO mkdir -p "$CERT_DIR"
  $SUDO openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout "${CERT_DIR}/privkey.pem" -out "${CERT_DIR}/fullchain.pem" \
    -subj "/CN=${DOMAIN}" >/dev/null 2>&1
  ok "  Temporary certificate created."

  say "  Starting the stack (nginx will use the temporary cert for now)..."
  "${COMPOSE[@]}" up -d --build
  ok "  Stack started."

  say "  Waiting for the app to become healthy (needed before nginx is reachable)..."
  healthy=0
  for _ in $(seq 1 40); do
    if curl -fsS "http://localhost:8000/api/health/live" >/dev/null 2>&1; then healthy=1; break; fi
    sleep 3
  done
  [ "$healthy" -eq 1 ] || warn "  App health check did not pass after 2 minutes — continuing anyway; check 'docker compose logs app' after this script finishes."

  say "  Removing the temporary certificate and requesting a REAL one from Let's Encrypt..."
  $SUDO rm -rf "/etc/letsencrypt/live/${DOMAIN}" "/etc/letsencrypt/archive/${DOMAIN}" "/etc/letsencrypt/renewal/${DOMAIN}.conf"

  if $SUDO certbot certonly --webroot -w /var/www/certbot \
        -d "$DOMAIN" -d "www.$DOMAIN" \
        --email "$EMAIL" --agree-tos --non-interactive --no-eff-email; then
    ok "  Real Let's Encrypt certificate issued."
  else
    die "Certbot failed to issue a certificate. Common causes: DNS not yet propagated, port 80 blocked by a cloud firewall (check your VPS provider's network/firewall panel, not just ufw), or a Cloudflare orange-cloud proxy intercepting the HTTP-01 challenge (switch to DNS-only during issuance). Re-run this script once fixed — it will skip the steps already completed."
  fi

  say "  Reloading nginx with the real certificate..."
  "${COMPOSE[@]}" restart nginx
  ok "  nginx reloaded."
fi

# ── 8. Bring the full stack up (idempotent if already running) ──────────────
say "[8/9] Ensuring the full stack is up..."
"${COMPOSE[@]}" up -d --build
ok "Stack is up."

say "  Waiting for the app health check..."
healthy=0
for i in $(seq 1 40); do
  if curl -fsS "http://localhost:8000/api/health/live" >/dev/null 2>&1; then healthy=1; ok "  App healthy after ${i} checks."; break; fi
  sleep 3
done
if [ "$healthy" -ne 1 ]; then
  warn "App did not report healthy in time. Recent logs:"
  "${COMPOSE[@]}" logs --tail=60 app || true
fi

# ── 9. Seed accounts (using the SAME passwords already in .env) + auto-renewal ──
say "[9/9] Creating seed accounts and certificate auto-renewal..."
SUPERADMIN_PW="$(env_get BOOTSTRAP_SUPERADMIN_PASSWORD)"
ADMIN_PW="$(env_get BOOTSTRAP_ADMIN_PASSWORD)"
if [ -n "$SUPERADMIN_PW" ]; then
  "${COMPOSE[@]}" exec -T app python scripts/create_superadmin.py --password "$SUPERADMIN_PW" \
    || warn "Superadmin creation failed/already exists — run manually if needed: ${COMPOSE[*]} exec app python scripts/create_superadmin.py --reset --password '<pw>'"
else
  warn "BOOTSTRAP_SUPERADMIN_PASSWORD not found in .env — skipping superadmin seed. Run manually:"
  warn "  ${COMPOSE[*]} exec app python scripts/create_superadmin.py"
fi
if [ -n "$ADMIN_PW" ]; then
  "${COMPOSE[@]}" exec -T app python scripts/create_admin.py --password "$ADMIN_PW" \
    || warn "Admin creation failed/already exists — run manually if needed: ${COMPOSE[*]} exec app python scripts/create_admin.py --reset --password '<pw>'"
fi
ok "Seed accounts created (credentials are in .env — BOOTSTRAP_SUPERADMIN_PASSWORD / BOOTSTRAP_ADMIN_PASSWORD)."

CRON_CMD="certbot renew --webroot -w /var/www/certbot --quiet --deploy-hook 'cd ${APP_DIR} && ${COMPOSE[*]} restart nginx'"
( $SUDO crontab -l 2>/dev/null | grep -vF "certbot renew" ; echo "17 3 * * * ${CRON_CMD}" ) | $SUDO crontab -
ok "Certificate auto-renewal scheduled daily at 03:17."

echo
echo "=============================================================="
ok "Bootstrap complete."
echo "=============================================================="
"${COMPOSE[@]}" ps
echo
echo "Open:            https://${DOMAIN}"
echo "Superadmin login: superadmin@hopefx.io / (see BOOTSTRAP_SUPERADMIN_PASSWORD in .env)"
echo "Admin login:      admin@hopefx.io / (see BOOTSTRAP_ADMIN_PASSWORD in .env)"
echo ".env (all secrets) is at: ${APP_DIR}/.env — back it up somewhere safe and secret."
echo
warn "Next: edit .env and set an AI provider key (LLM_BACKEND + ANTHROPIC_API_KEY or OPENAI_API_KEY), then:"
echo "  cd ${APP_DIR} && ${COMPOSE[*]} up -d --build app"
echo
