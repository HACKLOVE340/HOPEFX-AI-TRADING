# Deployment Guide

> Current version: **v1.17** — Python 3.12 required (matches the `python:3.12-slim` Docker image).
> API server listens on port **8000**.
>
> This previously read "Python 3.10, 3.11, or 3.12" while the install commands below
> fetched 3.10. CI tests 3.11 and 3.12, production runs 3.12, and the committed `.pkl`
> artifacts are pickled on 3.12 — so 3.10 was tested by nothing and loads those
> artifacts at the reader's risk. See the Gotchas section of CLAUDE.md.
> Last updated: 2026-04-01

## Prerequisites

- Linux server (Ubuntu 22.04+ recommended)
- Python 3.12 (must match the Docker image — `python:3.12-slim`)
- Redis 7+
- PostgreSQL 16+ (for production; SQLite used automatically in development)
- Docker + Docker Compose (recommended)
- 4+ GB RAM (8 GB recommended for ML training)
- 20+ GB disk space

## Deployment Options

### Option 1: Docker Deployment (Recommended)

#### 1. Install Docker and Docker Compose

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt-get update
sudo apt-get install docker-compose
```

#### 2. Clone Repository

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
```

#### 3. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit with production values
nano .env
```

**Required environment variables:**
```bash
# Security — generate unique values for each deployment
SECURITY_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
HOPEFX_KILL_SWITCH_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))")

# Subscription license key — required for all trading endpoints
# Obtain from hopefx.com/pricing after subscribing
# Without this, /api/trading/, /api/signals/, /api/ml/ return 403
HOPEFX_LICENSE_KEY=HOPEFX-PRO-XXXXXXXX-XXXX

# Database
POSTGRES_PASSWORD=$(python -c "import secrets; print(secrets.token_hex(16))")
POSTGRES_USER=hopefx_admin
DATABASE_URL=postgresql://hopefx_admin:${POSTGRES_PASSWORD}@postgres:5432/hopefx_db

# Application
APP_ENV=production
LOG_LEVEL=INFO
```

Validate all secrets before starting:
```bash
python scripts/manage_secrets.py validate
# Expected: All required secrets are valid.
```

#### 4. Build and Start

```bash
# Build images
docker-compose build

# Start services
docker-compose up -d

# Check logs
docker-compose logs -f hopefx-app
```

#### 5. Verify Deployment

```bash
# Check health
curl http://localhost:8000/health

# Check admin panel
open http://localhost:8000/admin

# Check API docs
open http://localhost:8000/docs
```

---

### Option 2: Systemd Service Deployment

#### 1. Prepare System

```bash
# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install dependencies. 3.12 is not a preference: the committed model
# artifacts under ml/saved_models/ are pickled by CI on 3.12, and a
# different interpreter here loads them at your own risk.
sudo apt-get install -y python3.12 python3.12-venv python3.12-dev python3-pip redis-server postgresql
```

#### 2. Create Application User

```bash
sudo useradd -r -m -s /bin/bash hopefx
sudo mkdir -p /opt/hopefx-ai-trading
sudo chown hopefx:hopefx /opt/hopefx-ai-trading
```

#### 3. Install Application

```bash
# Switch to hopefx user
sudo -u hopefx -i

# Clone repository
cd /opt/hopefx-ai-trading
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git .

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### 4. Configure Database

```bash
# Create PostgreSQL database
sudo -u postgres psql << EOF
CREATE DATABASE hopefx_trading;
CREATE USER hopefx_admin WITH ENCRYPTED PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE hopefx_trading TO hopefx_admin;
EOF
```

#### 5. Configure Application

```bash
# Copy environment template
cp .env.example .env

# Edit configuration
nano .env
```

#### 6. Install Systemd Service

```bash
# Copy service file
sudo cp hopefx-trading.service /etc/systemd/system/

# Create log directory
sudo mkdir -p /var/log/hopefx
sudo chown hopefx:hopefx /var/log/hopefx

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable hopefx-trading
sudo systemctl start hopefx-trading

# Check status
sudo systemctl status hopefx-trading

# View logs
sudo journalctl -u hopefx-trading -f
```

---

## Security Configuration

### 1. Firewall Setup

```bash
# Enable UFW
sudo ufw enable

# Allow SSH
sudo ufw allow 22/tcp

# Allow application port (use reverse proxy in production)
sudo ufw allow 8000/tcp

# Check status
sudo ufw status
```

### 2. SSL/TLS with Nginx (Production)

```bash
# Install Nginx
sudo apt-get install nginx certbot python3-certbot-nginx

# Create Nginx configuration
sudo nano /etc/nginx/sites-available/hopefx
```

**Nginx configuration:**
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/hopefx /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Get SSL certificate
sudo certbot --nginx -d your-domain.com
```

### 3. Environment Security

```bash
# Restrict .env file permissions
chmod 600 .env

# Encrypt sensitive data
# (Use ansible-vault or similar for production)
```

---

## Monitoring Setup

### 1. Application Monitoring

```bash
# Check application health
curl http://localhost:8000/health

# View system metrics
curl http://localhost:8000/admin/api/system-info
```

### 2. Log Monitoring

```bash
# Application logs
tail -f logs/hopefx_ai.log

# Error logs
tail -f logs/error.log

# Systemd logs
sudo journalctl -u hopefx-trading -f
```

### 3. Resource Monitoring

```bash
# Install monitoring tools
sudo apt-get install htop iotop

# Monitor processes
htop

# Monitor disk I/O
sudo iotop
```

---

## Backup Strategy

### 1. Database Backups

```bash
# Create backup script
cat > /opt/hopefx-ai-trading/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/hopefx-ai-trading/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Backup PostgreSQL
pg_dump -U hopefx_admin hopefx_trading | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Backup configuration
tar -czf $BACKUP_DIR/config_$DATE.tar.gz .env credentials/

# Keep only last 30 days
find $BACKUP_DIR -name "*.gz" -mtime +30 -delete

echo "Backup completed: $DATE"
EOF

chmod +x /opt/hopefx-ai-trading/backup.sh
```

### 2. Automated Backups

```bash
# Add to crontab
crontab -e

# Run daily at 2 AM
0 2 * * * /opt/hopefx-ai-trading/backup.sh >> /var/log/hopefx/backup.log 2>&1
```

---

## Scaling Considerations

### Horizontal Scaling

1. **Load Balancer**: Use Nginx/HAProxy for load balancing
2. **Multiple Instances**: Run multiple app instances
3. **Shared Database**: All instances connect to same PostgreSQL
4. **Shared Redis**: All instances use same Redis cache

### Vertical Scaling

1. **Increase RAM**: Allocate more memory for ML models
2. **CPU Optimization**: Use multi-core processing
3. **SSD Storage**: Improve I/O performance

---

## Troubleshooting

### Application Won't Start

```bash
# Check logs
sudo journalctl -u hopefx-trading -n 50

# Verify dependencies
source venv/bin/activate
pip install -r requirements.txt

# Check database connection
psql -U hopefx_admin -d hopefx_trading

# Check Redis
redis-cli ping
```

### High Memory Usage

```bash
# Check process memory
ps aux | grep python

# Optimize settings in .env
# Reduce MAX_WORKERS, ASYNC_BUFFER_SIZE

# Restart application
sudo systemctl restart hopefx-trading
```

### Database Connection Issues

```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Test connection
psql -h localhost -U hopefx_admin -d hopefx_trading

# Check firewall
sudo ufw status
```

---

## Maintenance

### Regular Updates

```bash
# Backup first!
/opt/hopefx-ai-trading/backup.sh

# Pull latest code
git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt --upgrade

# Restart service
sudo systemctl restart hopefx-trading
```

### Log Rotation

```bash
# Create logrotate configuration
sudo nano /etc/logrotate.d/hopefx
```

```
/var/log/hopefx/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 hopefx hopefx
    sharedscripts
    postrotate
        systemctl reload hopefx-trading > /dev/null 2>&1 || true
    endscript
}
```

---

## Email Deliverability

HOPEFX sends transactional alerts via SendGrid (primary) with raw SMTP as a
fallback. Without proper DNS authentication, emails from a server IP land in
spam. Follow these steps before enabling live alerts.

### 1. SendGrid setup

1. Create a free SendGrid account at <https://sendgrid.com>.
2. Go to **Settings → Sender Authentication → Domain Authentication** and
   authenticate your sending domain (e.g. `hopefx.io`).
3. Copy the API key from **Settings → API Keys** and set it in your environment:

```env
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxx
SMTP_FROM=alerts@mail.hopefx.io
```

4. Configure the **Event Webhook** under **Settings → Mail Settings →
   Event Webhook**:
   - URL: `https://your-domain.com/api/email/webhook`
   - Events to enable: **Bounce**, **Spam Report**, **Unsubscribe**
   - This automatically suppresses future sends to bounced/unsubscribed
     addresses via the `email_suppressions` database table.

### 2. Required DNS records

Add these records to your domain's DNS. Replace `[YOUR_DOMAIN]` with your
actual domain (e.g. `hopefx.io`).

**SPF** — authorises SendGrid to send on your behalf:

```
Type:  TXT
Name:  @  (or mail.[YOUR_DOMAIN] for subdomain sending)
Value: v=spf1 include:sendgrid.net ~all
```

**DKIM** — cryptographic signature proving the email was not tampered with:

```
# SendGrid generates the DKIM keys during Domain Authentication.
# Copy the two CNAME records from the SendGrid dashboard and add them to DNS.
# Example (values will differ for your account):
Type:  CNAME
Name:  s1._domainkey.[YOUR_DOMAIN]
Value: s1.domainkey.u12345678.wl123.sendgrid.net

Type:  CNAME
Name:  s2._domainkey.[YOUR_DOMAIN]
Value: s2.domainkey.u12345678.wl123.sendgrid.net
```

**DMARC** — policy that tells receiving servers what to do with unauthenticated
mail. Start with `p=none` (monitor only) and tighten to `p=quarantine` once
SPF and DKIM are confirmed passing:

```
Type:  TXT
Name:  _dmarc.[YOUR_DOMAIN]
Value: v=DMARC1; p=quarantine; rua=mailto:dmarc@[YOUR_DOMAIN]
```

**Sending subdomain recommendation:**

Use `mail.[YOUR_DOMAIN]` (e.g. `mail.hopefx.io`) as the sending domain rather
than the root domain. This isolates transactional email reputation from your
main domain and simplifies SPF alignment.

```env
SMTP_FROM=alerts@mail.hopefx.io
```

### 3. Verify DNS propagation

After adding records, verify with:

```bash
# SPF
dig TXT mail.hopefx.io +short

# DMARC
dig TXT _dmarc.hopefx.io +short

# DKIM (replace s1 with your selector)
dig CNAME s1._domainkey.hopefx.io +short
```

Or use <https://mxtoolbox.com/SuperTool.aspx> for a browser-based check.

### 4. Test send

```bash
# Confirm the /health endpoint reports email as healthy
curl -s https://your-domain.com/health | python3 -m json.tool | grep email
# Expected: "email": "healthy"
```

---

## Production Checklist

### Secrets & Subscription
- [ ] `SECURITY_JWT_SECRET` generated (≥ 32 chars, not a placeholder)
- [ ] `CONFIG_ENCRYPTION_KEY` generated (≥ 32 chars, not a placeholder)
- [ ] `HOPEFX_KILL_SWITCH_TOKEN` generated (≥ 32 chars, not a placeholder)
- [ ] `HOPEFX_LICENSE_KEY` set and validated (`python scripts/manage_secrets.py validate`)
- [ ] `APP_ENV=production` set

### Infrastructure
- [ ] PostgreSQL configured with strong password
- [ ] SSL/TLS configured with Nginx + Let's Encrypt
- [ ] Firewall configured (UFW: allow 22, 80, 443 only)
- [ ] Automated database backups scheduled (daily, 30-day retention)
- [ ] Log rotation configured (`/etc/logrotate.d/hopefx`)
- [ ] Monitoring enabled (Prometheus + Grafana)
- [ ] Alerting configured (Telegram + email)

### Validation
- [ ] `python scripts/manage_secrets.py validate` — all green
- [ ] `python deployment_guide.py` — all checks pass
- [ ] `curl https://your-domain.com/health` — all components healthy
- [ ] `curl https://your-domain.com/api/monetization/subscription/me` — plan active
- [ ] Test disaster recovery procedure documented

---

## FIX Protocol Onboarding

The FIX adapter (`execution/fix_adapter.py`) requires real broker credentials
before it will connect in `APP_ENV=production`.

### Required environment variables

| Variable | Description |
|---|---|
| `FIX_SENDER_COMP_ID` | Your firm's SenderCompID assigned by the broker |
| `FIX_TARGET_COMP_ID` | Broker's TargetCompID from their FIX spec |
| `FIX_HOST` | Broker FIX gateway hostname |
| `FIX_PORT` | Broker FIX gateway port |

### Broker endpoints

| Broker | Environment | Host | Port |
|---|---|---|---|
| OANDA | Practice | `fxpractice-fix.oanda.com` | 1234 |
| OANDA | Live | `fxtrade-fix.oanda.com` | 1234 |
| IBKR TWS | Paper | `127.0.0.1` | 7497 |
| IBKR TWS | Live | `127.0.0.1` | 7496 |

### Setup steps

1. Copy the template: `cp fix.cfg fix.cfg.local`
2. Fill in all `<CHANGE_ME_*>` values in `fix.cfg.local`
3. Set `FIX_CONFIG_FILE=fix.cfg.local` in your `.env`
4. Set `FIX_SENDER_COMP_ID`, `FIX_TARGET_COMP_ID`, `FIX_HOST`, `FIX_PORT` in `.env`
5. Run the pre-flight check: `python deployment_guide.py`
6. **Never commit `fix.cfg.local`** — it contains credentials (already in `.gitignore`)

---

---

## Option 3: Kubernetes / Helm

### Prerequisites

```bash
# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Install Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### Create Secrets

```bash
kubectl create namespace hopefx

kubectl create secret generic hopefx-secrets \
  --namespace hopefx \
  --from-literal=SECURITY_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))") \
  --from-literal=CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
  --from-literal=HOPEFX_KILL_SWITCH_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))") \
  --from-literal=HOPEFX_LICENSE_KEY=HOPEFX-PRO-XXXXXXXX-XXXX \
  --from-literal=DATABASE_URL=postgresql://hopefx:password@postgres:5432/hopefx_db \
  --from-literal=REDIS_URL=redis://redis:6379/0
```

### Deploy with Helm

```bash
helm upgrade --install hopefx helm/hopefx/ \
  --namespace hopefx \
  --set image.tag=latest \
  --set app.env=production \
  --atomic \
  --timeout 5m

kubectl rollout status deployment/hopefx --namespace hopefx
```

### Check Status

```bash
kubectl get pods --namespace hopefx
kubectl logs -f deployment/hopefx --namespace hopefx
kubectl exec -it deployment/hopefx --namespace hopefx -- curl localhost:8000/health
```

### Rollback

```bash
helm rollback hopefx --namespace hopefx
```

---

## Option 4: VPS with systemd (Minimal)

For a single VPS without Docker:

### 1. Provision the VPS

Minimum: 2 vCPU, 4 GB RAM, 20 GB SSD (Ubuntu 22.04).

```bash
# Update and install system deps
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3.12-dev \
  git nginx certbot python3-certbot-nginx \
  postgresql postgresql-contrib redis-server
```

### 2. Create Application User

```bash
sudo useradd -m -s /bin/bash hopefx
sudo su - hopefx
```

### 3. Clone and Install

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with production values — minimum required:
#   SECURITY_JWT_SECRET, CONFIG_ENCRYPTION_KEY, HOPEFX_KILL_SWITCH_TOKEN
#   HOPEFX_LICENSE_KEY, DATABASE_URL, APP_ENV=production
nano .env
# Validate all secrets before proceeding
python scripts/manage_secrets.py validate
alembic upgrade head
exit
```

### 4. Install the systemd Service

```bash
sudo cp hopefx-trading.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hopefx-trading
sudo systemctl start hopefx-trading
sudo systemctl status hopefx-trading
```

### 5. Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/hopefx
```

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/hopefx /etc/nginx/sites-enabled/
sudo certbot --nginx -d yourdomain.com
sudo nginx -t && sudo systemctl reload nginx
```

### 6. Configure Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

### 7. Verify

```bash
curl https://yourdomain.com/health
```

---

## Updating a Running Deployment

### Docker Compose

```bash
git pull origin main
docker compose pull
docker compose up -d --no-deps --build app
docker compose logs -f app
```

### Kubernetes

```bash
git pull origin main
docker build -t hopefx:$(git rev-parse --short HEAD) .
docker push your-registry/hopefx:$(git rev-parse --short HEAD)
helm upgrade hopefx helm/hopefx/ \
  --namespace hopefx \
  --set image.tag=$(git rev-parse --short HEAD) \
  --atomic
```

### VPS systemd

```bash
sudo su - hopefx
cd HOPEFX-AI-TRADING
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
exit
sudo systemctl restart hopefx-trading
sudo systemctl status hopefx-trading
```

---

## Database Migrations

Always run migrations before restarting the application:

```bash
# Check current revision
alembic current

# Apply all pending migrations
alembic upgrade head

# Rollback one migration (if needed)
alembic downgrade -1
```

The latest migration is `f1a2b3c4d5e6` (watchlists table).

---

## Support

For deployment issues:
- GitHub Issues: https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues
- Documentation: See [INSTALLATION.md](INSTALLATION.md), [SECURITY.md](SECURITY.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

*Last updated: 2026-04-01 (v1.17)*
