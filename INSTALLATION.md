# Installation Guide

## Prerequisites

- **Python 3.10, 3.11, or 3.12** (3.10 minimum — f-strings with `=` specifier required)
- Git
- Redis 7+ (optional — rate limiting and caching fall back to in-memory without it)
- PostgreSQL 16+ (optional — SQLite is used automatically in development)

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
# Standard install (all features)
pip install -r requirements.txt

# CI / lightweight (no C extensions, no GPU deps)
pip install -r requirements-ci.txt

# Development (editable install + dev tools)
pip install -e ".[dev]"
```

### 4. Configure environment

```bash
cp .env.example .env
```

Minimum required variables — the app will not start without these:

```bash
SECURITY_JWT_SECRET=<48-char random string>
CONFIG_ENCRYPTION_KEY=<48-char random string>
```

Generate them:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 5. Start the server

```bash
# Development (auto-reload)
uvicorn app:app --reload --port 8000

# Swagger UI: http://localhost:8000/docs
```

### 6. Paper trading quickstart

```bash
python quickstart.py
```

---

## Docker (recommended for production)

```bash
docker-compose up -d
```

This starts the full stack: FastAPI app + PostgreSQL 16 + Redis 7 + Prometheus + Grafana.
See [`DEPLOYMENT.md`](DEPLOYMENT.md) for production hardening steps.

---

## Optional broker packages

These are not included in `requirements.txt` to avoid pulling platform-specific binaries:

| Broker | Package | Install |
|---|---|---|
| MetaTrader 5 | `MetaTrader5` | `pip install MetaTrader5` |
| Interactive Brokers | `ib_insync` | `pip install ib_insync` |
| Binance / CCXT | `ccxt` | `pip install ccxt` |

---

## Redis (optional)

Without Redis, rate limiting and caching use in-memory fallbacks. For production, install Redis:

**Ubuntu/Debian:**
```bash
sudo apt-get install redis-server
sudo systemctl enable --now redis-server
```

**macOS:**
```bash
brew install redis && brew services start redis
```

---

## PostgreSQL (optional)

SQLite is used automatically when `DATABASE_URL` is not set. For production:

**Ubuntu/Debian:**
```bash
sudo apt-get install postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

**macOS:**
```bash
brew install postgresql && brew services start postgresql
```

Set `DATABASE_URL=postgresql://user:pass@localhost:5432/hopefx` in `.env`.

---

## Verification

```bash
# Check Python version (must be 3.10+)
python --version

# Verify core imports
python -c "import fastapi, sqlalchemy, sklearn; print('OK')"

# Health check (server must be running)
curl http://localhost:8000/health
```

---

## Troubleshooting

**`CONFIG_ENCRYPTION_KEY not set`**
```bash
export CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

**`Redis connection failed`**
The app falls back to in-memory automatically. To use Redis: `redis-cli ping` to verify it is running.

**`ImportError: No module named X`**
```bash
pip install -r requirements.txt
```

**`Permission denied` on logs/ or data/**
```bash
chmod 755 logs data credentials
```

---

## Next steps

- [SETUP_GUIDE.md](SETUP_GUIDE.md) — detailed environment configuration
- [DEPLOYMENT.md](DEPLOYMENT.md) — production deployment (Docker, Kubernetes, systemd)
- [SECURITY.md](SECURITY.md) — security hardening checklist
- [CONTRIBUTING.md](CONTRIBUTING.md) — development workflow
