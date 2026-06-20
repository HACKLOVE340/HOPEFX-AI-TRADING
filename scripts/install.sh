#!/usr/bin/env bash
# scripts/install.sh — one-command setup for Linux/macOS/WSL.
#   CPU (default):  bash scripts/install.sh
#   NVIDIA GPU:     bash scripts/install.sh gpu
set -euo pipefail
DEVICE="${1:-cpu}"
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
if [ "$DEVICE" = "gpu" ]; then
  pip install torch --index-url https://download.pytorch.org/whl/cu121
else
  pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
pip install -r requirements.txt
echo
echo "Done. Optional: pip install tensorflow ; pip install -r requirements-dev.txt"
echo "Verify: python scripts/check_feeds.py"
