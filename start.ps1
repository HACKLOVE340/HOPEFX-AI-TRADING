# HOPEFX AI Trading - Windows PowerShell quick-start
# Usage:
#   .\start.ps1              (development mode, port 8000)
#   .\start.ps1 --port 8080  (custom port)
#
# If blocked by execution policy, run once:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#
# Uses a venv to avoid pip cache permission errors (Errno 13) on Windows.

param(
    [string]$Port = "",
    [switch]$NoReload
)

Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"

# ── Check Python ──────────────────────────────────────────────────────────────
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Install from https://python.org and add to PATH."
    exit 1
}

# ── Create virtual environment if missing ─────────────────────────────────────
if (-not (Test-Path "venv\Scripts\Activate.ps1")) {
    Write-Host "[INFO] Creating virtual environment..." -ForegroundColor Cyan
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create venv. Check Python installation."
        exit 1
    }
}

# ── Activate venv ─────────────────────────────────────────────────────────────
& "venv\Scripts\Activate.ps1"

# ── Bootstrap: generate .env and seed users if not present ───────────────────
if (-not (Test-Path ".env")) {
    Write-Host "[INFO] .env not found -- running dev bootstrap..." -ForegroundColor Cyan
    python scripts\bootstrap_dev.py
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Bootstrap failed. See output above."
        exit 1
    }
}

# ── Load .env into current process environment ────────────────────────────────
Get-Content ".env" | Where-Object { $_ -notmatch "^\s*#" -and $_ -match "=" } | ForEach-Object {
    $parts = $_ -split "=", 2
    [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
}

# ── Install / update dependencies ─────────────────────────────────────────────
python -c "import uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Installing dependencies..." -ForegroundColor Cyan
    pip install --no-cache-dir -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install failed. See output above."
        exit 1
    }
}

# ── Install MetaTrader5 if not present (Windows only) ─────────────────────────
python -c "import MetaTrader5" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Installing MetaTrader5 SDK..." -ForegroundColor Cyan
    pip install --no-cache-dir "MetaTrader5>=5.0.45"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] MetaTrader5 install failed. MT5 broker will be unavailable." -ForegroundColor Yellow
    } else {
        Write-Host "[INFO] MetaTrader5 installed successfully." -ForegroundColor Green
    }
}

# ── Frontend build ────────────────────────────────────────────────────────────
if (-not (Test-Path "static\index.html")) {
    Write-Host "[INFO] Frontend not built -- attempting npm build..." -ForegroundColor Cyan
    if ((Get-Command npm -ErrorAction SilentlyContinue) -and (Test-Path "frontend\package.json")) {
        Push-Location frontend
        npm install --silent
        npm run build
        Pop-Location
    } else {
        Write-Host "[WARN] npm not found or frontend missing -- skipping. API will still start." -ForegroundColor Yellow
    }
} else {
    Write-Host "[INFO] Frontend already built." -ForegroundColor Green
}

# ── Environment defaults ──────────────────────────────────────────────────────
$apiHost = if ($env:API_HOST) { $env:API_HOST } else { "127.0.0.1" }
$apiPort = if ($Port)         { $Port }         elseif ($env:API_PORT) { $env:API_PORT } else { "8000" }

Write-Host ""
Write-Host "  HOPEFX AI Trading Framework" -ForegroundColor Cyan
Write-Host "  -------------------------------------------------"
Write-Host "  Login:        http://localhost:$apiPort/login"
Write-Host "  SuperAdmin:   http://localhost:$apiPort/api/superadmin/"
Write-Host "  Admin:        http://localhost:$apiPort/api/admin/"
Write-Host "  API Docs:     http://localhost:$apiPort/docs"
Write-Host "  Health:       http://localhost:$apiPort/health"
Write-Host "  -------------------------------------------------"
Write-Host "  Credentials:  see .env  (BOOTSTRAP_SUPERADMIN_PASSWORD)"
Write-Host "  -------------------------------------------------"
Write-Host ""

# ── Start server ──────────────────────────────────────────────────────────────
$uvicornArgs = @("app:app", "--host", $apiHost, "--port", $apiPort)
if (-not $NoReload) { $uvicornArgs += "--reload" }

python -m uvicorn @uvicornArgs
