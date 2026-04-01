# Installation

> Full installation guide for Linux, macOS, and Windows.
> Last updated: 2026-04-01

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.10 | 3.12 |
| RAM | 4 GB | 8 GB |
| CPU | 2 cores | 4+ cores |
| Storage | 10 GB | 20 GB |
| OS | Ubuntu 20.04 / macOS 12 / Windows 10 | Ubuntu 22.04 / macOS 14 |

---

## Option A — Local Python Install (Development)

### 1. Install Python

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev git -y
```

**macOS (Homebrew):**
```bash
brew install python@3.12 git
```

**Windows:**
Download Python 3.12 from [python.org](https://www.python.org/downloads/).
During install, check "Add Python to PATH".

### 2. Clone the Repository

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
```

### 3. Create a Virtual Environment

```bash
python3.12 -m venv venv

# Activate
source venv/bin/activate          # Linux/macOS
venv\Scripts\activate             # Windows (Command Prompt)
venv\Scripts\Activate.ps1         # Windows (PowerShell)
```

### 4. Install Dependencies

```bash
# Core dependencies
pip install -r requirements.txt

# Optional: ML extras (TensorFlow, PyTorch, TA-Lib)
pip install -r requirements-optional.txt

# Development tools (testing, linting)
pip install -r requirements-dev.txt
```

### 5. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` — at minimum set these four values:
```bash
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECURITY_JWT_SECRET=<48-char random hex>
CONFIG_ENCRYPTION_KEY=<48-char random hex>
HOPEFX_KILL_SWITCH_TOKEN=<48-char random hex>

# Subscription license key — required for trading endpoints
# Obtain from hopefx.com/pricing or request a trial via GitHub Issues (label: trial-request)
# Without this, all /api/trading/, /api/signals/, and /api/ml/ endpoints return 403
HOPEFX_LICENSE_KEY=HOPEFX-PRO-XXXXXXXX-XXXX
```

Generate all secrets at once:
```bash
python -c "
import secrets
print('SECURITY_JWT_SECRET=' + secrets.token_hex(32))
print('CONFIG_ENCRYPTION_KEY=' + secrets.token_hex(32))
print('HOPEFX_KILL_SWITCH_TOKEN=' + secrets.token_hex(32))
"
```

Validate all secrets before proceeding:
```bash
python scripts/manage_secrets.py validate
# Expected: All required secrets are valid.
```

### 6. Initialize the Database

```bash
alembic upgrade head
```

### 7. Start the Server

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

---

## Option B — Docker Compose (Recommended for Production)

### Prerequisites

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Install Docker Compose
sudo apt install docker-compose-plugin -y
```

### Start All Services

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

# Configure environment
cp .env.example .env
# Edit .env with your secrets and broker credentials

# Start everything (app + PostgreSQL + Redis)
docker compose up -d

# Check logs
docker compose logs -f app
```

Services started:
- `app` — FastAPI server on port 8000
- `trading` — background trading engine
- `postgres` — PostgreSQL 16 on port 5432
- `redis` — Redis 7 on port 6379
- `prometheus` — metrics on port 9090
- `grafana` — dashboards on port 3000

### Health Check

```bash
curl http://localhost:8000/health
```

### Stop Services

```bash
docker compose down
# To also remove volumes (wipes database):
docker compose down -v
```

---

## Option C — Docker Single Container

For minimal setups without PostgreSQL/Redis:

```bash
docker build -t hopefx .
docker run -d \
  --name hopefx \
  -p 8000:8000 \
  -e SECURITY_JWT_SECRET=your_secret \
  -e CONFIG_ENCRYPTION_KEY=your_key \
  -e HOPEFX_KILL_SWITCH_TOKEN=your_token \
  -e DATABASE_URL=sqlite:///./hopefx.db \
  -v $(pwd)/data:/app/data \
  hopefx
```

---

## Optional Dependencies

### Redis (Recommended)

Redis enables the ML feature cache (1-min TTL), WebSocket pub/sub, and rate limiting.

```bash
# Ubuntu
sudo apt install redis-server -y
sudo systemctl enable redis-server
sudo systemctl start redis-server

# macOS
brew install redis
brew services start redis

# Add to .env
REDIS_URL=redis://localhost:6379/0
```

### PostgreSQL (Recommended for Production)

SQLite works for development. Use PostgreSQL for production.

```bash
# Ubuntu
sudo apt install postgresql postgresql-contrib -y
sudo -u postgres createuser hopefx
sudo -u postgres createdb hopefx_db -O hopefx
sudo -u postgres psql -c "ALTER USER hopefx PASSWORD 'your_password';"

# Add to .env
DATABASE_URL=postgresql://hopefx:your_password@localhost:5432/hopefx_db
```

### TA-Lib (Optional — for advanced technical indicators)

TA-Lib requires a system library:

```bash
# Ubuntu
sudo apt install libta-lib-dev -y
pip install TA-Lib

# macOS
brew install ta-lib
pip install TA-Lib

# Windows — download the wheel from:
# https://github.com/cgohlke/talib-build/releases
pip install TA_Lib-0.4.28-cp312-cp312-win_amd64.whl
```

### MetaTrader 5 (Windows only)

MT5 Python API only works on Windows:
```bash
pip install MetaTrader5
```

---

## Windows-Specific Notes

### Long Path Support

Enable long paths in Windows (required for some dependencies):
```powershell
# Run as Administrator
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1
```

### WSL2 (Recommended for Windows)

WSL2 gives the best compatibility on Windows. All Linux features work inside WSL2,
including Redis, PostgreSQL, and Docker. MT5 is the only feature that requires
native Windows (not WSL2).

```powershell
# Install WSL2 with Ubuntu 22.04 (run as Administrator)
wsl --install -d Ubuntu-22.04

# After reboot, open Ubuntu from the Start menu
# Then follow the Linux installation steps inside WSL2
```

Inside WSL2, access the app from Windows at `http://localhost:8000` — WSL2 forwards
ports to Windows automatically.

**WSL2 + Docker Desktop:** Enable "Use WSL2 based engine" in Docker Desktop settings.
Then `docker compose up -d` works from inside WSL2.

**File system performance:** Clone the repository inside WSL2 (`~/projects/HOPEFX-AI-TRADING`),
not on the Windows file system (`/mnt/c/...`). The Windows file system is 10–50x slower
for Python operations.

### Windows Firewall

If the server is not reachable from other machines, allow port 8000:
```powershell
netsh advfirewall firewall add rule name="HOPEFX" dir=in action=allow protocol=TCP localport=8000
```

---

## Verifying the Installation

```bash
# Check Python version
python --version
# Expected: Python 3.10.x, 3.11.x, or 3.12.x

# Check core imports
python -c "import fastapi, sqlalchemy, pydantic; print('Core OK')"

# Check ML imports
python -c "import xgboost, sklearn, pandas, numpy; print('ML OK')"

# Validate all secrets (including license key)
python scripts/manage_secrets.py validate
# Expected: All required secrets are valid.

# Run the test suite
pytest tests/ -q --tb=short
# Expected: 2560 passed, 0 failed (some skips for optional deps)

# Check the server starts
uvicorn app:app --host 0.0.0.0 --port 8000 &
sleep 3
curl http://localhost:8000/health
# Expected: {"status":"healthy","components":{"license":"valid",...}}
kill %1
```

### Subscription Verification

After the server starts, confirm your license key is active:

```bash
# Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your_pass"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Check subscription status
curl http://localhost:8000/api/monetization/subscription/me \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"plan":"professional","status":"active",...}
```

If you see `403 Subscription Required`, your `HOPEFX_LICENSE_KEY` is missing or invalid.
Run `python scripts/manage_secrets.py validate` to diagnose.

---

## Upgrading

```bash
git pull origin main
pip install -r requirements.txt --upgrade
alembic upgrade head
```

If there are breaking changes, check [CHANGELOG.md](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/CHANGELOG.md) first.

---

## Uninstalling

```bash
# Stop the server
pkill -f "uvicorn app:app"

# Remove the virtual environment
deactivate
rm -rf venv/

# Remove Docker containers and volumes
docker compose down -v
docker rmi hopefx

# Remove the repository
cd ..
rm -rf HOPEFX-AI-TRADING/
```

---

## Next Steps

- [Quick Start](QUICKSTART.md) — get your first signal in 15 minutes
- [Setup Guide](SETUP_GUIDE.md) — broker configuration
- [Deployment](DEPLOYMENT.md) — production deployment
- [Troubleshooting](TROUBLESHOOTING.md) — common installation errors
