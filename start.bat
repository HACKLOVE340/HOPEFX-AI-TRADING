@echo off
:: HOPEFX AI Trading - Windows quick-start
:: Usage:
::   start.bat              (development mode, port 8000)
::   start.bat --port 8080  (custom port)
::
:: Requirements: Python 3.10+
:: First run creates a venv, installs all dependencies, and generates .env.
:: Using a venv avoids pip cache permission errors (Errno 13) on Windows.

setlocal EnableDelayedExpansion

cd /d "%~dp0"

:: ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org and add to PATH.
    pause
    exit /b 1
)

:: ── Create virtual environment if missing ─────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv. Check Python installation.
        pause
        exit /b 1
    )
)

:: ── Activate venv ─────────────────────────────────────────────────────────────
call venv\Scripts\activate.bat

:: ── Bootstrap: generate .env and seed users if not present ───────────────────
if not exist ".env" (
    echo [INFO] .env not found -- running dev bootstrap...
    python scripts\bootstrap_dev.py
    if errorlevel 1 (
        echo [ERROR] Bootstrap failed. See output above.
        pause
        exit /b 1
    )
)

:: ── Install / update dependencies ─────────────────────────────────────────────
:: requirements-windows.txt excludes Linux-only packages (uvloop, triton,
:: nvidia-*, cuda-*) that have no Windows wheels and would cause install failures.
python -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing dependencies from requirements-windows.txt...
    pip install --no-cache-dir -r requirements-windows.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed. See output above.
        pause
        exit /b 1
    )
)

:: ── Install MetaTrader5 if not present (Windows only, non-fatal) ──────────────
python -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing MetaTrader5 SDK...
    pip install --no-cache-dir "MetaTrader5>=5.0.45"
    if errorlevel 1 (
        echo [WARN] MetaTrader5 install failed. MT5 broker will be unavailable.
    ) else (
        echo [INFO] MetaTrader5 installed successfully.
    )
)

:: ── Frontend build ────────────────────────────────────────────────────────────
if not exist "static\index.html" (
    echo [INFO] Frontend not built -- attempting npm build...
    where npm >nul 2>&1
    if not errorlevel 1 (
        if exist "frontend\package.json" (
            cd frontend
            npm install --silent && npm run build
            cd ..
        )
    ) else (
        echo [WARN] npm not found -- skipping frontend build. API will still start.
    )
) else (
    echo [INFO] Frontend already built.
)

:: ── Environment defaults ──────────────────────────────────────────────────────
if not defined APP_ENV  set APP_ENV=development
if not defined API_HOST set API_HOST=127.0.0.1
if not defined API_PORT set API_PORT=8000

echo.
echo   HOPEFX AI Trading Framework
echo   -------------------------------------------------
echo   Login:        http://localhost:%API_PORT%/login
echo   SuperAdmin:   http://localhost:%API_PORT%/api/superadmin/
echo   Admin:        http://localhost:%API_PORT%/api/admin/
echo   API Docs:     http://localhost:%API_PORT%/docs
echo   Health:       http://localhost:%API_PORT%/health
echo   -------------------------------------------------
echo   Credentials:  see .env  (BOOTSTRAP_SUPERADMIN_PASSWORD)
echo   -------------------------------------------------
echo.

:: ── Start server ──────────────────────────────────────────────────────────────
python -m uvicorn app:app --host %API_HOST% --port %API_PORT% --reload %*
