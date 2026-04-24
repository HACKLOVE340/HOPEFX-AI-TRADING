# HOPEFX AI Trading — Windows test launcher (PowerShell)
# ============================================================
# Usage:
#   .\start.ps1              (port 8000)
#   .\start.ps1 -Port 8080   (custom port)
#   .\start.ps1 -NoReload    (disable hot-reload)
#
# Requirements: Python 3.12, Node.js (for frontend build)
#
# If blocked by execution policy, run once:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#
# What this does on every run:
#   1. Creates a venv on first run (avoids pip cache permission errors)
#   2. Syncs ALL dependencies from requirements-windows.txt
#   3. Installs MetaTrader5 SDK if not present
#   4. Builds the React frontend if not already built
#   5. Generates .env if not present
#   6. Starts the API server with hot-reload
# ============================================================

param(
    [string]$Port    = "",
    [switch]$NoReload
)

Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"

# ── 1. Check Python 3.12 ──────────────────────────────────────────────────────
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python not found. Install Python 3.12 from https://python.org" -ForegroundColor Red
    exit 1
}
$pyVer = (python --version 2>&1) -replace "Python ", ""
$parts = $pyVer -split "\."
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 12)) {
    Write-Host "[ERROR] Python 3.12+ required. Found $pyVer." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python $pyVer" -ForegroundColor Green

# ── 2. Create venv if missing ─────────────────────────────────────────────────
if (-not (Test-Path "venv\Scripts\Activate.ps1")) {
    Write-Host "[INFO] Creating virtual environment..." -ForegroundColor Cyan
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create venv." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Virtual environment created" -ForegroundColor Green
}

# ── 3. Activate venv ──────────────────────────────────────────────────────────
& "venv\Scripts\Activate.ps1"

# ── 4. Clear pip cache (prevents [Errno 13] Permission denied on cached wheels) ─
# Windows locks .whl files in the pip cache after a failed or interrupted install.
# Purging before every install guarantees pip always downloads fresh — no lock conflicts.
Write-Host "[INFO] Clearing pip cache..." -ForegroundColor Cyan
pip cache purge 2>$null
Write-Host "[OK] Pip cache cleared" -ForegroundColor Green

# ── 5. Always sync dependencies ───────────────────────────────────────────────
# Runs on every start so new packages added after git pull are always installed.
# pip skips packages already up to date — fast after first run.
Write-Host "[INFO] Syncing dependencies..." -ForegroundColor Cyan
pip install --no-cache-dir -r requirements-windows.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Dependency install failed. See output above." -ForegroundColor Red
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
    Write-Host "[INFO] Generating .env via dev bootstrap..." -ForegroundColor Cyan
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

# ── 9. Build frontend if not built ────────────────────────────────────────────
if (-not (Test-Path "static\index.html")) {
    Write-Host "[INFO] Building React frontend..." -ForegroundColor Cyan
    if ((Get-Command npm -ErrorAction SilentlyContinue) -and (Test-Path "frontend\package.json")) {
        Push-Location frontend
        npm install --silent
        npm run build
        Pop-Location
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[WARN] Frontend build failed. API will still start without UI." -ForegroundColor Yellow
        } else {
            Write-Host "[OK] Frontend built" -ForegroundColor Green
        }
    } else {
        Write-Host "[WARN] npm not found. Skipping frontend build. API will still start." -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] Frontend already built" -ForegroundColor Green
}

# ── 10. Set defaults and start ────────────────────────────────────────────────
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

$uvicornArgs = @("app:app", "--host", $apiHost, "--port", $apiPort)
if (-not $NoReload) { $uvicornArgs += "--reload" }

python -m uvicorn @uvicornArgs
