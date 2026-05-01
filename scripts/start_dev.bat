@echo off
REM HOPEFX AI Trading — Development startup script (Windows)
REM Usage: scripts\start_dev.bat

setlocal enabledelayedexpansion
cd /d "%~dp0\.."

echo [HOPEFX] Starting HOPEFX AI Trading development server...

REM ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    pause & exit /b 1
)

REM ── Check Node ───────────────────────────────────────────────────────────────
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install Node.js 20+ from https://nodejs.org
    pause & exit /b 1
)

REM ── Create .env if missing ────────────────────────────────────────────────────
if not exist ".env" (
    echo [HOPEFX] .env not found - running bootstrap...
    python scripts\bootstrap_dev.py
)

REM ── Install Python deps ───────────────────────────────────────────────────────
echo [HOPEFX] Installing Python dependencies...
pip install -q --upgrade pip
pip install -q "uvicorn[standard]" fastapi sqlalchemy aiosqlite python-dotenv ^
  "pydantic[email]" redis "python-jose[cryptography]" "passlib[bcrypt]" ^
  python-multipart httpx aiohttp yfinance pandas numpy joblib xgboost PyJWT

REM ── Install frontend deps ─────────────────────────────────────────────────────
echo [HOPEFX] Installing frontend dependencies...
cd frontend
npm install --silent
cd ..

REM ── Build frontend ────────────────────────────────────────────────────────────
echo [HOPEFX] Building frontend...
cd frontend
npm run build
cd ..

REM ── Bootstrap DB ─────────────────────────────────────────────────────────────
echo [HOPEFX] Bootstrapping database...
python scripts\bootstrap_dev.py 2>nul

REM ── Start backend ─────────────────────────────────────────────────────────────
echo [HOPEFX] Starting FastAPI backend on http://localhost:8000 ...
set APP_ENV=development
start "HOPEFX Backend" /B python -m uvicorn app:app --host 0.0.0.0 --port 8000

REM ── Wait for backend ──────────────────────────────────────────────────────────
echo [HOPEFX] Waiting for backend to be ready...
:WAIT_LOOP
timeout /t 2 /nobreak >nul
curl -sf http://localhost:8000/health >nul 2>&1
if errorlevel 1 goto WAIT_LOOP
echo [HOPEFX] Backend is ready.

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║  HOPEFX AI Trading — Development Server Running      ║
echo ║                                                       ║
echo ║  Backend API:  http://localhost:8000                  ║
echo ║  API Docs:     http://localhost:8000/docs             ║
echo ║  Frontend:     Served by FastAPI at /                 ║
echo ║                                                       ║
echo ║  Login:        http://localhost:8000/login            ║
echo ║  Superadmin:   superadmin@hopefx.io                   ║
echo ║  Trader:       trader@hopefx.io                       ║
echo ║                                                       ║
echo ║  Close this window to stop the server                 ║
echo ╚══════════════════════════════════════════════════════╝
echo.

REM Keep window open
pause
