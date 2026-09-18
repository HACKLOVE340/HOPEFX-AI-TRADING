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

# Local inference runtime. Installed by default because a deployment that wants
# a local model and does not have Ollama gets a local chain leg that can never
# answer -- and the runtime, correctly, refuses to start rather than pretend.
# Skip it with NO_LOCAL_AI=1 on a box that will only use hosted models.
if [ "${NO_LOCAL_AI:-0}" = "1" ]; then
  echo "Skipping Ollama (NO_LOCAL_AI=1). Hosted models are unaffected."
else
  bash "$(dirname "$0")/install_ollama.sh" || {
    echo "WARNING: Ollama did not install. Hosted models still work; the local" >&2
    echo "         leg will refuse to start until you run scripts/install_ollama.sh." >&2
  }
fi

echo
echo "Done. Optional: pip install tensorflow ; pip install -r requirements-dev.txt"
echo "Verify: python scripts/check_feeds.py"
echo "Local model tier for THIS machine: python scripts/vps_capability_report.py"
