@echo off
:: HOPEFX AI Trading — Windows test launcher
:: ============================================================
:: Usage:
::   start.bat              (port 8000)
::   start.bat --port 8080  (custom port)
::
:: Requirements: Python 3.12, Node.js (for frontend build)
::
:: What this does on every run:
::   1. Creates a venv on first run (avoids pip cache permission errors)
::   2. Syncs ALL dependencies from requirements-windows.txt
::   3. Installs MetaTrader5 SDK if not present
::   4. Builds the React frontend if not already built
::   5. Generates .env if not present
::   6. Starts the API server with hot-reload
:: ============================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ── 1. Check Python 3.12 ─────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.12 from https://python.org
    pause & exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if %PY_MAJOR% LSS 3 (
    echo [ERROR] Python 3.12+ required. Found %PY_VER%.
    pause & exit /b 1
)
if %PY_MINOR% LSS 12 (
    echo [ERROR] Python 3.12+ required. Found %PY_VER%.
    pause & exit /b 1
)
echo [OK] Python %PY_VER%

:: ── 2. Create venv if missing ─────────────────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        pause & exit /b 1
    )
    echo [OK] Virtual environment created
)

:: ── 3. Activate venv ──────────────────────────────────────────────────────────
call venv\Scripts\activate.bat

:: ── 4. Clear pip cache (prevents [Errno 13] Permission denied on cached wheels) ─
:: Windows locks .whl files in the pip cache after a failed or interrupted install.
:: Purging before every install guarantees pip always downloads fresh — no lock conflicts.
echo [INFO] Clearing pip cache...
pip cache purge >nul 2>&1
echo [OK] Pip cache cleared

:: ── 5. Always sync dependencies ───────────────────────────────────────────────
:: Runs on every start so new packages added after git pull are always installed.
:: pip skips packages already up to date — fast after first run.
echo [INFO] Syncing dependencies...
pip install --no-cache-dir -r requirements-windows.txt
if errorlevel 1 (
    echo [ERROR] Dependency install failed. See output above.
    pause & exit /b 1
)
echo [OK] Dependencies synced

:: ── 6. MetaTrader5 (Windows only, non-fatal) ──────────────────────────────────
python -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing MetaTrader5 SDK...
    pip install --no-cache-dir -q "MetaTrader5>=5.0.45"
    if errorlevel 1 (
        echo [WARN] MetaTrader5 install failed. MT5 broker will be unavailable.
    ) else (
        echo [OK] MetaTrader5 installed
    )
) else (
    echo [OK] MetaTrader5 present
)

:: ── 7. Generate .env if missing ───────────────────────────────────────────────
if not exist ".env" (
    echo [INFO] Generating .env via dev bootstrap...
    python scripts\bootstrap_dev.py
    if errorlevel 1 (
        echo [ERROR] Bootstrap failed. See output above.
        pause & exit /b 1
    )
    echo [OK] .env generated
) else (
    echo [OK] .env found
)

:: ── 8. Build frontend if not built ────────────────────────────────────────────
if not exist "static\index.html" (
    echo [INFO] Building React frontend...
    where npm >nul 2>&1
    if not errorlevel 1 (
        if exist "frontend\package.json" (
            cd frontend
            npm install --silent && npm run build
            if errorlevel 1 (
                echo [WARN] Frontend build failed. API will still start without UI.
            ) else (
                echo [OK] Frontend built
            )
            cd ..
        )
    ) else (
        echo [WARN] npm not found. Skipping frontend build. API will still start.
    )
) else (
    echo [OK] Frontend already built
)

:: ── 9. Set defaults and start ─────────────────────────────────────────────────
if not defined APP_ENV  set APP_ENV=development
if not defined API_HOST set API_HOST=127.0.0.1
if not defined API_PORT set API_PORT=8000

echo.
echo   ============================================================
echo   HOPEFX AI Trading
echo   ============================================================
echo   Login      : http://localhost:%API_PORT%/login
echo   Dashboard  : http://localhost:%API_PORT%/dashboard
echo   API Docs   : http://localhost:%API_PORT%/docs
echo   Health     : http://localhost:%API_PORT%/api/health/live
echo   Credentials: see .env  (BOOTSTRAP_SUPERADMIN_PASSWORD)
echo   ============================================================
echo   Press Ctrl+C to stop
echo.

python -m uvicorn app:app --host %API_HOST% --port %API_PORT% --reload %*
