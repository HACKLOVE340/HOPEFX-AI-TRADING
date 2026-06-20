# scripts/install.ps1 — one-command setup for Windows.
#   CPU (default):  .\scripts\install.ps1
#   NVIDIA GPU:     .\scripts\install.ps1 -Device gpu
#   skip venv:      .\scripts\install.ps1 -NoVenv
param(
  [ValidateSet("cpu","gpu")][string]$Device = "cpu",
  [switch]$NoVenv
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
Write-Host ""
Write-Host "Done. Optional extras (install only if you need them):"
Write-Host "  pip install tensorflow            # LSTM deep models"
Write-Host "  pip install MetaTrader5           # only for the MT5 broker (Windows)"
Write-Host "  conda install -c conda-forge ta-lib   # technical-indicator C lib"
Write-Host "Verify:  python scripts\check_feeds.py"
