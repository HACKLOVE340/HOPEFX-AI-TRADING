# DEPLOYMENT GUIDE

Complete deployment guide for HOPEFX AI Trading Framework in production.

## Prerequisites

- Linux server (Ubuntu 20.04+ recommended)
- Python 3.8+
- Redis
- PostgreSQL (for production)
- Docker (optional, recommended)
- 2+ GB RAM
- 10+ GB disk space

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
# Security (CRITICAL - Generate unique values!)
CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
CONFIG_SALT=$(python -c "import secrets; print(secrets.token_hex(16))")

# Database
POSTGRES_PASSWORD=$(python -c "import secrets; print(secrets.token_hex(16))")
POSTGRES_USER=hopefx_admin

# Application
APP_ENV=production
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
curl http://localhost:5000/health

# Check admin panel
open http://localhost:5000/admin

# Check API docs
open http://localhost:5000/docs
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
sudo ufw allow 5000/tcp

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
        proxy_pass http://localhost:5000;
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
curl http://localhost:5000/health

# View system metrics
curl http://localhost:5000/admin/api/system-info
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

---

## Support

For deployment issues:
- GitHub Issues: https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues
- Documentation: See INSTALLATION.md, SECURITY.md

---

**Status:** Production deployment guide complete.
