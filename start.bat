@echo off
:: HOPEFX AI Trading — Windows launcher
:: ============================================================
:: Usage:
::   start.bat              (port 8000)
::   start.bat --port 8080  (custom port)
::
:: Requirements: Python 3.10+, Node.js (for frontend build)
::
:: What this does:
::   1. Checks Python 3.10+
::   2. Creates a venv on first run
::   3. Installs dependencies ONLY on first run or when requirements.txt changes
::   4. Installs MetaTrader5 SDK if not present (Windows only)
::   5. Generates .env if not present
::   6. Builds the React frontend if not already built
::   7. Starts the API server with hot-reload
:: ============================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ── 1. Check Python 3.10+ ────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
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
        echo [ERROR] Failed to create venv.
        pause & exit /b 1
    )
    echo [OK] Virtual environment created
)

:: ── 3. Activate venv ──────────────────────────────────────────────────────────
call venv\Scripts\activate.bat

:: ── 4. Sync dependencies only when requirements.txt changes ──────────────────
:: Hash-check: MD5 of requirements.txt is stored in venv/.req_hash.
:: pip only runs on first launch or after requirements.txt is modified.
python -c "import hashlib,os,sys; f='venv\\.req_hash'; h=hashlib.md5(open('requirements.txt','rb').read()).hexdigest(); sys.exit(0 if os.path.exists(f) and open(f).read().strip()==h else 1)" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Requirements changed — syncing dependencies...
    pip cache purge >nul 2>&1
    pip install --no-cache-dir -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. See output above.
        pause & exit /b 1
    )
    python -c "import hashlib; open('venv\\.req_hash','w').write(hashlib.md5(open('requirements.txt','rb').read()).hexdigest())"
    echo [OK] Dependencies synced
) else (
    echo [OK] Dependencies up to date
)

:: ── 5. MetaTrader5 (Windows only, non-fatal) ──────────────────────────────────
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

:: ── 6. Generate .env if missing ───────────────────────────────────────────────
:: NOTE: Do NOT parse .env here — security risk.
:: Secrets are loaded by python-dotenv inside the application at startup.
:: Parsing .env in a batch loop exposes all secrets as OS-level env vars
:: visible to every child process and in process listings.
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

:: ── 7. Build frontend if missing OR stale (code changed since last build) ─────
:: static\ is a gitignored build artifact. Rebuild when the checked-out commit
:: differs from the one stamped in static\.build-commit, so pulling new code
:: doesn't silently keep serving the old UI.
set "CURRENT_COMMIT="
for /f %%i in ('git rev-parse HEAD 2^>nul') do set "CURRENT_COMMIT=%%i"
set "BUILT_COMMIT="
if exist "static\.build-commit" set /p BUILT_COMMIT=<static\.build-commit
set "NEED_BUILD=0"
if not exist "static\index.html" set "NEED_BUILD=1"
if not "%CURRENT_COMMIT%"=="%BUILT_COMMIT%" set "NEED_BUILD=1"
if "%NEED_BUILD%"=="1" (
    echo [INFO] Building React frontend ^(missing or stale^)...
    where npm >nul 2>&1
    if not errorlevel 1 (
        if exist "frontend\package.json" (
            pushd frontend
            npm install --silent && npm run build
            set "BUILD_RC=!errorlevel!"
            popd
            if "!BUILD_RC!"=="0" (
                echo %CURRENT_COMMIT%>static\.build-commit
                echo [OK] Frontend built
            ) else (
                echo [WARN] Frontend build failed. API will still start without UI.
            )
        )
    ) else (
        echo [WARN] npm not found. Skipping frontend build. API will still start.
    )
) else (
    echo [OK] Frontend already built and up to date
)

:: ── 8. Set defaults and start ─────────────────────────────────────────────────
if not defined APP_ENV  set APP_ENV=development
if not defined API_HOST set API_HOST=127.0.0.1
if not defined API_PORT set API_PORT=8000

:: Dev convenience: without Postgres/Redis the readiness gate would hold data
:: endpoints (and the SPA) at 503 on a plain SQLite setup. Open the gate in
:: development so the app serves immediately. Production (APP_ENV=production)
:: keeps the gate ON — provision Postgres/Redis there.
if /i "%APP_ENV%"=="development" if not defined STARTUP_GATE set STARTUP_GATE=false

echo.
echo   ============================================================
echo   HOPEFX AI Trading
echo   ============================================================
echo   Login      : http://localhost:%API_PORT%/login
echo   SuperAdmin : http://localhost:%API_PORT%/api/superadmin/
echo   Admin      : http://localhost:%API_PORT%/api/admin/
echo   Dashboard  : http://localhost:%API_PORT%/dashboard
echo   API Docs   : http://localhost:%API_PORT%/docs
echo   Health     : http://localhost:%API_PORT%/api/health/live
echo   ============================================================
echo   Credentials: see .env  (BOOTSTRAP_SUPERADMIN_PASSWORD)
echo   ============================================================
echo   Press Ctrl+C to stop
echo.

:: NOTE: no --reload by default. A bare --reload watches the whole project
:: (venv, the SQLite .db, logs, and the json/yara files the self-healer and
:: antivirus write at startup) and restarts in an endless loop on Windows.
:: For code hot-reload during development, append --reload yourself.
python -m uvicorn app:app --host %API_HOST% --port %API_PORT% %*
