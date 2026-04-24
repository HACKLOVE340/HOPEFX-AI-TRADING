@echo off
:: HOPEFX AI Trading — Windows launcher
:: ============================================================
:: Usage:
::   start.bat              (port 8000)
::   start.bat --port 8080  (custom port)
::
:: What this does on every run:
::   1. Verifies Python 3.10+
::   2. Creates venv on first run
::   3. Upgrades pip (inside venv only — never touches system Python)
::   4. Installs / syncs all dependencies with --no-cache-dir
::      (eliminates [Errno 13] Permission denied on Windows pip cache)
::   5. Installs MetaTrader5 SDK if not present (non-fatal)
::   6. Generates .env on first run
::   7. Builds React frontend if not already built
::   8. Starts the API server
:: ============================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ── 1. Verify Python 3.10+ ───────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python not found.
    echo         Install Python 3.10+ from https://python.org
    echo         Tick "Add Python to PATH" during installation.
    echo.
    pause & exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if %PY_MAJOR% LSS 3 (
    echo [ERROR] Python 3.10+ required. Found %PY_VER%.
    pause & exit /b 1
)
if %PY_MINOR% LSS 10 (
    echo [ERROR] Python 3.10+ required. Found %PY_VER%.
    pause & exit /b 1
)
echo [OK] Python %PY_VER%

:: ── 2. Create venv if missing ─────────────────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to create virtual environment.
        echo         Try running as Administrator (right-click -> Run as administrator).
        echo.
        pause & exit /b 1
    )
    echo [OK] Virtual environment created
)

:: ── 3. Activate venv ──────────────────────────────────────────────────────────
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    echo         Delete the venv\ folder and run start.bat again.
    pause & exit /b 1
)

:: ── 4. Upgrade pip (inside venv only) ────────────────────────────────────────
echo [INFO] Upgrading pip...
python -m pip install --no-cache-dir --quiet --upgrade pip
echo [OK] pip ready

:: ── 5. Install / sync all dependencies ───────────────────────────────────────
:: --no-cache-dir: bypasses the Windows pip cache entirely.
:: This is the definitive fix for [Errno 13] Permission denied on cached .whl files.
:: pip skips packages already at the correct version — fast after first run.
echo [INFO] Syncing dependencies...
pip install --no-cache-dir -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency install failed.
    echo.
    echo   Fixes to try:
    echo   1. Run as Administrator (right-click -> Run as administrator)
    echo   2. Temporarily disable antivirus / Windows Defender real-time protection
    echo   3. Delete venv\ and run start.bat again
    echo   4. Check your internet connection
    echo.
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
    echo [INFO] Generating .env with random secrets...
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
    where npm >nul 2>&1
    if not errorlevel 1 (
        if exist "frontend\package.json" (
            echo [INFO] Building React frontend...
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

:: ── 9. Start server ───────────────────────────────────────────────────────────
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
