# scripts/install.ps1 — one-command setup for Windows.
#   CPU (default):  .\scripts\install.ps1
#   NVIDIA GPU:     .\scripts\install.ps1 -Device gpu
#   skip venv:      .\scripts\install.ps1 -NoVenv
#   no local AI:    .\scripts\install.ps1 -NoLocalAI   (hosted models only)
param(
  [ValidateSet("cpu","gpu")][string]$Device = "cpu",
  [switch]$NoVenv,
  [switch]$NoLocalAI
)
$ErrorActionPreference = "Stop"
if (-not $NoVenv) {
  python -m venv .venv
  & .\.venv\Scripts\Activate.ps1
}
python -m pip install --upgrade pip
# 1) PyTorch first — correct build so the CUDA stack isn't pulled by accident.
if ($Device -eq "gpu") {
  pip install torch --index-url https://download.pytorch.org/whl/cu121
} else {
  pip install torch --index-url https://download.pytorch.org/whl/cpu
}
# 2) Everything else (core + all ML: sklearn, xgboost, lightgbm, SB3,
#    transformers, sentence-transformers, shap, optuna, numba, ...).
pip install -r requirements.txt
# Local inference runtime. Installed by default: a deployment that wants a local
# model and does not have Ollama gets a chain leg that can never answer, and the
# runtime refuses to start rather than pretend. Skip with -NoLocalAI.
if ($NoLocalAI) {
  Write-Host "Skipping Ollama (-NoLocalAI). Hosted models are unaffected."
} else {
  try {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'install_ollama.ps1')
  } catch {
    Write-Warning "Ollama did not install ($($_.Exception.Message)). Hosted models still work; the local leg will refuse to start until you run scripts\install_ollama.ps1."
  }
}

Write-Host ""
Write-Host "Done. Optional extras (install only if you need them):"
Write-Host "  pip install tensorflow            # LSTM deep models"
Write-Host "  pip install MetaTrader5           # only for the MT5 broker (Windows)"
Write-Host "  conda install -c conda-forge ta-lib   # technical-indicator C lib"
Write-Host "Verify:  python scripts\check_feeds.py"
Write-Host "Local model tier for THIS machine:  python scripts\vps_capability_report.py"
