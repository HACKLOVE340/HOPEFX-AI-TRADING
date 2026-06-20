# HOPEFX AI Trading — Windows launcher (PowerShell)
# ============================================================
# Usage:
#   .\start.ps1              (port 8000)
#   .\start.ps1 -Port 8080   (custom port)
#   .\start.ps1 -NoReload    (disable hot-reload)
#
# If blocked by execution policy, run once in PowerShell as Administrator:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#
# What this does on every run:
#   1. Verifies Python 3.10+
#   2. Creates venv on first run
#   3. Upgrades pip (inside venv only)
#   4. Installs / syncs all dependencies with --no-cache-dir
#      (eliminates [Errno 13] Permission denied on Windows pip cache)
#   5. Installs MetaTrader5 SDK if not present (non-fatal)
#   6. Generates .env on first run
#   7. Builds React frontend if not already built
#   8. Starts the API server
# ============================================================

param(
    [string]$Port    = "",
    [switch]$NoReload
)

Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"

# ── 1. Verify Python 3.10+ ────────────────────────────────────────────────────
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python not found." -ForegroundColor Red
    Write-Host "        Install Python 3.10+ from https://python.org" -ForegroundColor Red
    Write-Host "        Tick 'Add Python to PATH' during installation." -ForegroundColor Red
    exit 1
}
$pyVer = (python --version 2>&1) -replace "Python ", ""
$parts = $pyVer -split "\."
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    Write-Host "[ERROR] Python 3.10+ required. Found $pyVer." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python $pyVer" -ForegroundColor Green

# ── 2. Create venv if missing ─────────────────────────────────────────────────
if (-not (Test-Path "venv\Scripts\Activate.ps1")) {
    Write-Host "[INFO] Creating virtual environment..." -ForegroundColor Cyan
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        Write-Host "        Try running as Administrator." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Virtual environment created" -ForegroundColor Green
}

# ── 3. Activate venv ──────────────────────────────────────────────────────────
& "venv\Scripts\Activate.ps1"

# ── 4. Upgrade pip (inside venv only) ─────────────────────────────────────────
Write-Host "[INFO] Upgrading pip..." -ForegroundColor Cyan
python -m pip install --no-cache-dir --quiet --upgrade pip
Write-Host "[OK] pip ready" -ForegroundColor Green

# ── 5. Install / sync all dependencies ────────────────────────────────────────
# --no-cache-dir: bypasses the Windows pip cache entirely.
# This is the definitive fix for [Errno 13] Permission denied on cached .whl files.
# pip skips packages already at the correct version — fast after first run.
Write-Host "[INFO] Syncing dependencies..." -ForegroundColor Cyan
pip install --no-cache-dir -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Dependency install failed." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Fixes to try:" -ForegroundColor Yellow
    Write-Host "  1. Run as Administrator" -ForegroundColor Yellow
    Write-Host "  2. Temporarily disable antivirus / Windows Defender real-time protection" -ForegroundColor Yellow
    Write-Host "  3. Delete venv\ and run start.ps1 again" -ForegroundColor Yellow
    Write-Host "  4. Check your internet connection" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}
Write-Host "[OK] Dependencies synced" -ForegroundColor Green

# ── 6. MetaTrader5 (Windows only, non-fatal) ──────────────────────────────────
python -c "import MetaTrader5" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Installing MetaTrader5 SDK..." -ForegroundColor Cyan
    pip install --no-cache-dir -q "MetaTrader5>=5.0.45"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] MetaTrader5 install failed. MT5 broker will be unavailable." -ForegroundColor Yellow
    } else {
        Write-Host "[OK] MetaTrader5 installed" -ForegroundColor Green
    }
} else {
    Write-Host "[OK] MetaTrader5 present" -ForegroundColor Green
}

# ── 7. Generate .env if missing ───────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    Write-Host "[INFO] Generating .env with random secrets..." -ForegroundColor Cyan
    python scripts\bootstrap_dev.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Bootstrap failed. See output above." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] .env generated" -ForegroundColor Green
} else {
    Write-Host "[OK] .env found" -ForegroundColor Green
}

# ── 8. Load .env into process environment ─────────────────────────────────────
Get-Content ".env" | Where-Object { $_ -notmatch "^\s*#" -and $_ -match "=" } | ForEach-Object {
    $kv = $_ -split "=", 2
    [System.Environment]::SetEnvironmentVariable($kv[0].Trim(), $kv[1].Trim(), "Process")
}

# ── 9. Build frontend if missing OR stale (code changed since last build) ──────
# static\ is a gitignored build artifact. Rebuild when the checked-out commit
# differs from the one stamped in static\.build-commit, so pulling new code
# doesn't silently keep serving the old UI.
$currentCommit = (git rev-parse HEAD 2>$null)
if (-not $currentCommit) { $currentCommit = "unknown" }
$builtCommit = if (Test-Path "static\.build-commit") { (Get-Content "static\.build-commit" -Raw).Trim() } else { "none" }
$needBuild = (-not (Test-Path "static\index.html")) -or ($currentCommit -ne $builtCommit)
if ($needBuild) {
    if ((Get-Command npm -ErrorAction SilentlyContinue) -and (Test-Path "frontend\package.json")) {
        Write-Host "[INFO] Building React frontend (missing or stale)..." -ForegroundColor Cyan
        Push-Location frontend
        npm install --silent
        npm run build
        $buildRc = $LASTEXITCODE
        Pop-Location
        if ($buildRc -ne 0) {
            Write-Host "[WARN] Frontend build failed. API will still start without UI." -ForegroundColor Yellow
        } else {
            Set-Content -Path "static\.build-commit" -Value $currentCommit -NoNewline
            Write-Host "[OK] Frontend built" -ForegroundColor Green
        }
    } else {
        Write-Host "[WARN] npm not found. Skipping frontend build. API will still start." -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] Frontend already built and up to date" -ForegroundColor Green
}

# ── 10. Start server ──────────────────────────────────────────────────────────
$apiHost = if ($env:API_HOST) { $env:API_HOST } else { "127.0.0.1" }
$apiPort = if ($Port) { $Port } elseif ($env:API_PORT) { $env:API_PORT } else { "8000" }

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "  HOPEFX AI Trading" -ForegroundColor Cyan
Write-Host "  ============================================================"
Write-Host "  Login      : http://localhost:$apiPort/login"
Write-Host "  Dashboard  : http://localhost:$apiPort/dashboard"
Write-Host "  API Docs   : http://localhost:$apiPort/docs"
Write-Host "  Health     : http://localhost:$apiPort/api/health/live"
Write-Host "  Credentials: see .env  (BOOTSTRAP_SUPERADMIN_PASSWORD)"
Write-Host "  ============================================================"
Write-Host "  Press Ctrl+C to stop"
Write-Host ""

# Dev convenience: without Postgres/Redis the readiness gate holds the app at
# 503 on a SQLite-only setup. Open it in development; production keeps it on.
if (-not $env:APP_ENV) { $env:APP_ENV = "development" }
if ($env:APP_ENV -eq "development" -and -not $env:STARTUP_GATE) { $env:STARTUP_GATE = "false" }

$uvicornArgs = @("app:app", "--host", $apiHost, "--port", $apiPort)
# NOTE: no --reload by default. A bare --reload watches the whole project (venv,
# SQLite .db, logs, and the json/yara files the self-healer/antivirus write at
# startup) and restarts in an endless loop. For code hot-reload during
# development, append "--reload" when you call this script.

python -m uvicorn @uvicornArgs @args
