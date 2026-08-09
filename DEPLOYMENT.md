# Deployment Guide

> Current version: **v11.0.0** — Python 3.12 required (matches `python:3.12-slim` Docker image). API server listens on port **8000**.

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
python3 scripts/bootstrap_env.py --domain your-domain.com
```

This writes `.env` (mode 0600) from `.env.example` with a freshly generated value
for every secret, and prints the superadmin, admin, trader and Grafana passwords
once — **save them before you close the terminal.**

Do not copy `.env.example` by hand. It ships fourteen `CHANGE_ME_*` placeholders,
and startup validation rejects every one of them in production. A missed
placeholder does not announce itself; the deploy stops with

```
dependency failed to start: container hopefx-ai-trading-app-1 is unhealthy
```

which is `sys.exit(1)` inside startup validation, seen from outside the
container. To read the actual reason:

```bash
docker compose logs app | grep -A 20 "STARTUP VALIDATION FAILED"
```

Three of those placeholders also have to agree with each other —
`DATABASE_URL`, `POSTGRES_PASSWORD` and `DB_PASSWORD` are one credential written
three times — which is the part hand-editing tends to get wrong in a way that
only shows up as a database the app cannot log in to. The generator handles it.

Useful flags:

```bash
# regenerate over an existing .env (keeps a timestamped backup)
python3 scripts/bootstrap_env.py --domain your-domain.com --force

# NAME=VALUE lines only, for control-panel environment editors that
# import every line and choke on the '#' comments
python3 scripts/bootstrap_env.py --domain your-domain.com --no-comments
```

Things the generator deliberately leaves for you, because they come from
third-party accounts you set up after the platform is running:

| Variable | Needed for |
|----------|-----------|
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Billing. Set both, then `FEATURE_BILLING_SUBSCRIPTION=true` and restart. It ships **off** — left on with no webhook secret, startup validation hard-fails and the deploy never comes up. |
| `OANDA_API_KEY`, `OANDA_ACCOUNT_ID` | Live/practice OANDA execution. Paper trading works without them. |
| `FINNHUB_API_KEY` | Live economic calendar. Falls back to a hardcoded schedule. |
| `ANTHROPIC_API_KEY` | AI chat. Stub responses without it. |

None of these block startup.

#### 4. Build and Start

```bash
# Build images
docker compose build

# Start services
docker compose up -d

# Seed the superadmin account (uses BOOTSTRAP_SUPERADMIN_* from .env)
docker compose exec app python3 scripts/bootstrap_prod.py

# Check logs
docker compose logs -f app
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

# Install dependencies
sudo apt-get install -y python3.10 python3.10-venv python3-pip redis-server postgresql
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
python3.10 -m venv venv
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

## FIX Onboarding

The FIX protocol adapter (`execution/fix_adapter.py`) requires real broker
credentials before it will connect in production (`APP_ENV=production`).

### Required environment variables

| Variable | Description |
|---|---|
| `FIX_SENDER_COMP_ID` | Your firm's SenderCompID assigned by the broker |
| `FIX_TARGET_COMP_ID` | Broker's TargetCompID from their FIX spec |
| `FIX_HOST` | Broker FIX gateway hostname |
| `FIX_PORT` | Broker FIX gateway port (default: 1234 for OANDA) |

### Broker-specific notes

**OANDA FIX**
- Practice: `Host=fxpractice-fix.oanda.com Port=1234`
- Live: `Host=fxtrade-fix.oanda.com Port=1234`
- SenderCompID and TargetCompID are provided in the OANDA FIX onboarding email.
- Request FIX access via your OANDA account manager.

**IBKR TWS**
- Paper: `Host=127.0.0.1 Port=7497`
- Live: `Host=127.0.0.1 Port=7496`
- SenderCompID: assigned during IBKR FIX onboarding (contact IBKR support).
- TWS must be running locally or on the same host.

### Setup steps

1. Copy the template: `cp fix.cfg fix.cfg.local`
2. Fill in all `<CHANGE_ME_*>` values in `fix.cfg.local`
3. Set `FIX_CONFIG_FILE=fix.cfg.local` in your `.env`
4. Set `FIX_SENDER_COMP_ID`, `FIX_TARGET_COMP_ID`, `FIX_HOST`, `FIX_PORT` in `.env`
5. Run the pre-flight check: `python deployment_guide.py`
6. **Never commit `fix.cfg.local`** — it contains credentials (already in `.gitignore`)

---

## Production Checklist

- [ ] Set unique CONFIG_ENCRYPTION_KEY and CONFIG_SALT
- [ ] Configure PostgreSQL with strong password
- [ ] Set up SSL/TLS with Nginx
- [ ] Configure firewall (UFW)
- [ ] Set up automated backups
- [ ] Configure log rotation
- [ ] Enable monitoring
- [ ] Test disaster recovery
- [ ] Document custom configurations
- [ ] Set up alerting (Discord/Telegram/Email)
- [ ] Complete FIX onboarding with broker (see §FIX Onboarding above)
- [ ] Set FIX_SENDER_COMP_ID / FIX_TARGET_COMP_ID / FIX_HOST in .env
- [ ] Run `python deployment_guide.py` — all checks must pass

---

## Support

For deployment issues:
- GitHub Issues: https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues
- Documentation: See INSTALLATION.md, SECURITY.md

---

**Status:** Production deployment guide complete.
