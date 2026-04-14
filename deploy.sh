#!/usr/bin/env bash
# =============================================================================
# HOPEFX AI Trading — GoDaddy VPS Deployment Script
# =============================================================================
# Tested on: Ubuntu 22.04 LTS (GoDaddy VPS)
#
# Usage:
#   1. SSH into your VPS as root
#   2. Upload this file:  scp deploy.sh root@YOUR_VPS_IP:/root/
#   3. Make executable:   chmod +x deploy.sh
#   4. Run:               ./deploy.sh
#
# What this script does:
#   - Installs Docker, Docker Compose, Nginx, Certbot
#   - Clones the repo and configures .env
#   - Obtains a free Let's Encrypt SSL certificate
#   - Starts all services via docker compose
#   - Configures Nginx as the reverse proxy
#   - Sets up systemd service for auto-start on reboot
#   - Configures UFW firewall (ports 22, 80, 443 only)
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Require root ──────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Run as root: sudo ./deploy.sh"

# ── Configuration — edit these before running ─────────────────────────────────
DOMAIN="${DOMAIN:-}"                          # e.g. hopefx.io
EMAIL="${EMAIL:-}"                            # Let's Encrypt notifications
REPO_URL="${REPO_URL:-https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git}"
APP_DIR="${APP_DIR:-/opt/hopefx}"
DB_PASSWORD="${DB_PASSWORD:-}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"
JWT_SECRET="${JWT_SECRET:-}"
KILL_SWITCH_TOKEN="${KILL_SWITCH_TOKEN:-}"
ENCRYPTION_KEY="${ENCRYPTION_KEY:-}"

# ── Prompt for missing values ─────────────────────────────────────────────────
prompt() {
  local var="$1" prompt_text="$2" secret="${3:-false}"
  if [[ -z "${!var:-}" ]]; then
    if [[ "$secret" == "true" ]]; then  # pragma: allowlist secret
      # read into a nameref so shellcheck SC2229 is satisfied
      local -n _prompt_ref="$var"
      read -rsp "  $prompt_text: " _prompt_ref; echo
    else
      local -n _prompt_ref="$var"
      read -rp  "  $prompt_text: " _prompt_ref
    fi
    [[ -n "${!var}" ]] || die "$var cannot be empty"
  fi
}

echo ""
echo "============================================================"
echo "  HOPEFX AI Trading — VPS Deployment"
echo "============================================================"
echo ""

prompt DOMAIN          "Your domain name (e.g. hopefx.io)"
prompt EMAIL           "Email for Let's Encrypt notifications"
prompt DB_PASSWORD     "PostgreSQL password (strong, random)" true
prompt REDIS_PASSWORD  "Redis password (strong, random)"      true
prompt JWT_SECRET      "JWT secret (48+ random chars)"        true
prompt KILL_SWITCH_TOKEN "Kill-switch token (48+ random chars)" true
prompt ENCRYPTION_KEY  "Config encryption key (48 chars)"     true

# ── System update ─────────────────────────────────────────────────────────────
info "Updating system packages..."
apt-get update -qq && apt-get upgrade -y -qq
success "System updated"

# ── Install Docker ────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  info "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
  success "Docker installed"
else
  success "Docker already installed ($(docker --version))"
fi

# ── Install Docker Compose plugin ─────────────────────────────────────────────
if ! docker compose version &>/dev/null; then
  info "Installing Docker Compose plugin..."
  apt-get install -y -qq docker-compose-plugin
  success "Docker Compose installed"
else
  success "Docker Compose already installed"
fi

# ── Install Nginx ─────────────────────────────────────────────────────────────
if ! command -v nginx &>/dev/null; then
  info "Installing Nginx..."
  apt-get install -y -qq nginx
  success "Nginx installed"
else
  success "Nginx already installed"
fi

# ── Install Certbot ───────────────────────────────────────────────────────────
if ! command -v certbot &>/dev/null; then
  info "Installing Certbot..."
  apt-get install -y -qq certbot python3-certbot-nginx
  success "Certbot installed"
else
  success "Certbot already installed"
fi

# ── UFW Firewall ──────────────────────────────────────────────────────────────
info "Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp   comment "SSH"
ufw allow 80/tcp   comment "HTTP"
ufw allow 443/tcp  comment "HTTPS"
ufw --force enable
success "Firewall configured (22, 80, 443 open)"

# ── Clone / update repo ───────────────────────────────────────────────────────
if [[ -d "$APP_DIR/.git" ]]; then
  info "Updating existing repo at $APP_DIR..."
  git -C "$APP_DIR" pull --ff-only
else
  info "Cloning repo to $APP_DIR..."
  git clone "$REPO_URL" "$APP_DIR"
fi
success "Repo ready at $APP_DIR"

# ── Generate .env ─────────────────────────────────────────────────────────────
info "Writing .env..."
cat > "$APP_DIR/.env" <<EOF
# Auto-generated by deploy.sh — $(date -u +"%Y-%m-%dT%H:%M:%SZ")
APP_ENV=production
APP_BASE_URL=https://${DOMAIN}

# Security
SECURITY_JWT_SECRET=${JWT_SECRET}
CONFIG_ENCRYPTION_KEY=${ENCRYPTION_KEY}
HOPEFX_KILL_SWITCH_TOKEN=${KILL_SWITCH_TOKEN}
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
AUTH_RATE_LIMIT_REQUESTS=10
AUTH_RATE_LIMIT_WINDOW_SECONDS=60

# Database (PostgreSQL via docker compose)
DATABASE_URL=postgresql+asyncpg://hopefx:${DB_PASSWORD}@db:5432/hopefx
POSTGRES_USER=hopefx
POSTGRES_PASSWORD=${DB_PASSWORD}
POSTGRES_DB=hopefx
DB_HOST=db
DB_PASSWORD=${DB_PASSWORD}

# Redis
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=${REDIS_PASSWORD}

# CORS — only allow your domain
ALLOWED_ORIGINS=https://${DOMAIN},https://www.${DOMAIN}

# API
API_HOST=0.0.0.0
API_PORT=8000

# Broker (start in paper mode — switch to live after testing)
BROKER_TYPE=paper
INITIAL_BALANCE=100000
COMMISSION=3.5
PAPER_USER_ID=paper
SIGNAL_ENGINE_AUTO_TRADE=false

# Risk
RISK_MAX_POSITION_SIZE_PCT=0.05
RISK_MAX_DRAWDOWN_PCT=0.10
RISK_MAX_DAILY_LOSS_PCT=0.05
RISK_KELLY_FRACTION=0.25
RISK_MIN_RR=2.0

# ML
ML_MIN_TRADE_PROB=0.58
SL_ATR_MULT=1.5
TP_ATR_MULT=3.0

# AML
AML_SINGLE_WITHDRAWAL_CAP=10000
AML_DAILY_WITHDRAWAL_LIMIT=50000
AML_MAX_WITHDRAWALS_PER_DAY=5
AML_KYC_THRESHOLD=1000
EOF
chmod 600 "$APP_DIR/.env"
success ".env written (permissions: 600)"

# ── Configure Nginx ───────────────────────────────────────────────────────────
info "Configuring Nginx..."
sed "s/YOUR_DOMAIN/${DOMAIN}/g" "$APP_DIR/nginx/nginx.conf" \
  > /etc/nginx/nginx.conf

# Temporarily serve HTTP only so Certbot can complete the ACME challenge
cat > /etc/nginx/nginx.conf <<NGINX_TEMP
worker_processes auto;
events { worker_connections 1024; }
http {
  server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
  }
}
NGINX_TEMP

mkdir -p /var/www/certbot
nginx -t && systemctl reload nginx
success "Nginx temporary config loaded"

# ── Obtain SSL certificate ────────────────────────────────────────────────────
info "Obtaining Let's Encrypt certificate for ${DOMAIN}..."
certbot certonly --webroot \
  --webroot-path /var/www/certbot \
  --non-interactive \
  --agree-tos \
  --email "$EMAIL" \
  -d "$DOMAIN" \
  -d "www.${DOMAIN}" || warn "Certbot failed — check DNS points to this server. Re-run after fixing DNS."

# ── Install full Nginx config with SSL ────────────────────────────────────────
if [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  sed "s/YOUR_DOMAIN/${DOMAIN}/g" "$APP_DIR/nginx/nginx.conf" \
    > /etc/nginx/nginx.conf
  nginx -t && systemctl reload nginx
  success "Nginx SSL config loaded"
else
  warn "SSL cert not found — Nginx running HTTP-only until cert is obtained"
fi

# ── Auto-renew SSL ────────────────────────────────────────────────────────────
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && systemctl reload nginx") \
  | sort -u | crontab -
success "Certbot auto-renew cron installed (daily at 03:00)"

# ── Build and start Docker services ───────────────────────────────────────────
info "Building Docker image and starting services..."
cd "$APP_DIR"
docker compose pull --quiet
docker compose build --no-cache
docker compose up -d
success "Docker services started"

# ── Seed admin user ───────────────────────────────────────────────────────────
info "Seeding admin user..."
sleep 10  # wait for app container to be ready
docker compose exec -T app python3 scripts/bootstrap_dev.py || \
  warn "Bootstrap failed — run manually: docker compose exec app python3 scripts/bootstrap_dev.py"

# ── Systemd service for auto-start on reboot ──────────────────────────────────
info "Installing systemd service..."
cat > /etc/systemd/system/hopefx.service <<SYSTEMD
[Unit]
Description=HOPEFX AI Trading
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable hopefx
success "Systemd service installed (hopefx.service)"

# ── Health check ──────────────────────────────────────────────────────────────
info "Waiting for app to be healthy..."
for i in {1..12}; do
  if curl -sf "http://localhost:8000/health" | grep -q '"status":"healthy"'; then
    success "App is healthy"
    break
  fi
  sleep 5
  [[ $i -eq 12 ]] && warn "Health check timed out — check: docker compose logs app"
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo -e "  ${GREEN}Deployment complete!${NC}"
echo "============================================================"
echo ""
echo "  App URL  : https://${DOMAIN}"
echo "  API docs : https://${DOMAIN}/api/docs"
echo "  Health   : https://${DOMAIN}/health"
echo ""
echo "  Admin login (change password immediately):"
echo "    Email   : admin@hopefx.io"
echo "    Password: HopeFX-Admin-2025!"
echo ""
echo "  Useful commands:"
echo "    docker compose logs -f app     # live app logs"
echo "    docker compose ps              # service status"
echo "    docker compose restart app     # restart app"
echo "    docker compose down            # stop everything"
echo "    docker compose up -d           # start everything"
echo ""
echo "  IMPORTANT — do these now:"
echo "    1. Change the admin password at https://${DOMAIN}/settings"
echo "    2. Set BROKER_TYPE=live in .env when ready for live trading"
echo "    3. Add SMTP/SendGrid vars to .env to enable email alerts"
echo "    4. Review Grafana at port 3001 (add to UFW if needed)"
echo "============================================================"
