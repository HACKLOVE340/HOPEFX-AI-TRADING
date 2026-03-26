#!/usr/bin/env bash
# k6/run_load_test.sh
# ===================
# CI/CD wrapper for k6 load tests.
#
# Usage
# -----
#   ./k6/run_load_test.sh [SCENARIO] [BASE_URL]
#
#   SCENARIO  : smoke | load | soak | spike | stress | breakpoint (default: smoke)
#   BASE_URL  : API base URL (default: http://localhost:8000)
#
# Environment variables (override defaults)
#   AUTH_TOKEN    — Bearer token for authenticated endpoints
#   SIGNAL_SYMBOL — Symbol for signal/ML tests (default: XAUUSD)
#   K6_OUT        — k6 output format, e.g. "json=results/smoke.json"
#   K6_BINARY     — path to k6 binary (default: k6)
#
# Exit codes
#   0 — all thresholds passed
#   1 — one or more thresholds failed or k6 not found
#
# Install k6
# ----------
#   Linux:  sudo gpg -k && sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
#             --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69 && \
#           echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
#             | sudo tee /etc/apt/sources.list.d/k6.list && sudo apt-get update && sudo apt-get install k6
#   macOS:  brew install k6
#   Docker: docker run --rm -i grafana/k6 run - < k6/load_tests.js

set -euo pipefail

SCENARIO="${1:-smoke}"
BASE_URL="${2:-${BASE_URL:-http://localhost:8000}}"
K6_BINARY="${K6_BINARY:-k6}"
SCRIPT="$(dirname "$0")/load_tests.js"
RESULTS_DIR="$(dirname "$0")/results"

# ── Validate k6 is installed ──────────────────────────────────────────────────
if ! command -v "$K6_BINARY" &>/dev/null; then
  echo "ERROR: k6 not found. Install from https://k6.io/docs/get-started/installation/"
  echo ""
  echo "Quick install (Linux):"
  echo "  sudo apt-get install k6"
  echo ""
  echo "Quick install (macOS):"
  echo "  brew install k6"
  echo ""
  echo "Docker alternative (no install needed):"
  echo "  docker run --rm -i --network host grafana/k6 run \\"
  echo "    --env BASE_URL=${BASE_URL} --env SCENARIO=${SCENARIO} \\"
  echo "    - < k6/load_tests.js"
  exit 1
fi

# ── Validate scenario ─────────────────────────────────────────────────────────
VALID_SCENARIOS="smoke load soak spike stress breakpoint"
if ! echo "$VALID_SCENARIOS" | grep -qw "$SCENARIO"; then
  echo "ERROR: Unknown scenario '$SCENARIO'. Valid: $VALID_SCENARIOS"
  exit 1
fi

# ── Prepare results directory ─────────────────────────────────────────────────
mkdir -p "$RESULTS_DIR"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
RESULT_FILE="${RESULTS_DIR}/${SCENARIO}_${TIMESTAMP}.json"

# ── Build k6 args ─────────────────────────────────────────────────────────────
K6_ARGS=(
  run
  --env "BASE_URL=${BASE_URL}"
  --env "SCENARIO=${SCENARIO}"
  --env "SIGNAL_SYMBOL=${SIGNAL_SYMBOL:-XAUUSD}"
  --env "THINK_TIME=${THINK_TIME:-1.0}"
)

if [[ -n "${AUTH_TOKEN:-}" ]]; then
  K6_ARGS+=(--env "AUTH_TOKEN=${AUTH_TOKEN}")
fi

# Always write JSON results; allow override via K6_OUT
if [[ -n "${K6_OUT:-}" ]]; then
  K6_ARGS+=(--out "$K6_OUT")
else
  K6_ARGS+=(--out "json=${RESULT_FILE}")
fi

# Summary output
K6_ARGS+=(--summary-export "${RESULTS_DIR}/${SCENARIO}_${TIMESTAMP}_summary.json")

K6_ARGS+=("$SCRIPT")

# ── Run ───────────────────────────────────────────────────────────────────────
echo "========================================"
echo "  HOPEFX Load Test"
echo "  Scenario : ${SCENARIO}"
echo "  Base URL : ${BASE_URL}"
echo "  Results  : ${RESULT_FILE}"
echo "========================================"
echo ""

"$K6_BINARY" "${K6_ARGS[@]}"
EXIT_CODE=$?

echo ""
echo "========================================"
if [[ $EXIT_CODE -eq 0 ]]; then
  echo "  PASSED — all thresholds met"
else
  echo "  FAILED — one or more thresholds exceeded"
fi
echo "  Summary: ${RESULTS_DIR}/${SCENARIO}_${TIMESTAMP}_summary.json"
echo "========================================"

exit $EXIT_CODE
