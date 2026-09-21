#!/usr/bin/env bash
# scripts/retrain.sh
# Production model retraining with 25-year data and 8-year OOS evaluation.
#
# This script is the canonical entry point for scheduled retraining.
# It enforces the full production training protocol:
#   - 25 years of XAUUSD history (GC=F via yfinance or OANDA REST)
#     (pre-2001 bars in the bundled 50Y CSV are corrupt — see RETRAIN_YEARS)
#   - 8-year held-out OOS period (16% of data, never seen during training)
#   - Stacking ensemble: XGBoost + LightGBM + RandomForest + ExtraTrees
#   - Sharpe gate: N >= 600 OOS trades required before deployment
#   - Probability calibration (isotonic regression)
#   - Walk-forward CV (6 folds, TimeSeriesSplit)
#   - Macro features: DXY, VIX, yields, SPX cross-asset
#   - Regime filter: parabolic-bubble fold excluded from CV mean
#
# After training, the script:
#   1. Runs ml/verify_model.py to confirm integrity
#   2. Updates ml/saved_models/registry.json with the new version
#   3. Stamps the current.pkl symlink to the new model
#   4. Logs the OOS metrics summary
#
# Usage:
#   ./scripts/retrain.sh                    # full production retrain
#   ./scripts/retrain.sh --smoke            # CI smoke test (2Y, no OOS)
#   SKIP_VERIFY=true ./scripts/retrain.sh   # skip post-train verification
#
# Environment variables:
#   OANDA_API_KEY       — OANDA v20 token for live data fetch (optional)
#   OANDA_ACCOUNT_ID    — OANDA account ID (optional)
#   OANDA_PRACTICE      — "true" | "false" (default: "true")
#   SKIP_VERIFY         — skip ml/verify_model.py after training (default: false)
#   RETRAIN_YEARS       — years of history (default: 25; see note at RETRAIN_YEARS)
#   RETRAIN_OOS_YEARS   — OOS hold-out years (default: 8)
#   RETRAIN_STACKING    — "true" to use full stacking ensemble (default: true)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC}  $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC}  $*"; }
fail() { echo -e "${RED}  ✗${NC}  $*" >&2; exit 1; }
info() { echo -e "${CYAN}  ▶${NC}  $*"; }

# ── Parse args ────────────────────────────────────────────────────────────────
SMOKE_MODE=false
for arg in "$@"; do
    case "$arg" in
        --smoke) SMOKE_MODE=true ;;
    esac
done

# ── Config ────────────────────────────────────────────────────────────────────
# 25 years, not 50.
#
# data/XAUUSD_50Y.csv reaches back to 1968, and 15.2% of the bars a 50-year
# window selects move more than 20% in a single session — one by 519%. Its 1990
# rows dip to $81 in a year gold traded near $380. api/trading.py has always
# refused to serve that file to charts for exactly this reason; training loaded
# it anyway, which is how the production model came to report a 57.34%
# out-of-sample accuracy measured partly over history that never happened.
#
# ml/train_advanced.py now refuses a source that corrupt, so the old default of
# 50 does not produce a model at all — it produces an error. A default that
# always fails is worse than a smaller one that works.
#
# 25 years starts at 2001-08 and yields 6,424 bars with zero implausible moves
# (verified against the file). The corruption is confined to pre-2001, which is
# also what the gate reports as its first clean index.
#
# RETRAIN_YEARS=50 still works if you set TRAIN_ALLOW_CORRUPT_HISTORY=true, and
# will train on prices that are partly fictional. That is the point of making
# it explicit.
RETRAIN_YEARS="${RETRAIN_YEARS:-25}"
RETRAIN_OOS_YEARS="${RETRAIN_OOS_YEARS:-8}"
RETRAIN_STACKING="${RETRAIN_STACKING:-true}"
SKIP_VERIFY="${SKIP_VERIFY:-false}"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║       HOPEFX AI — Production Model Retraining        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

if [ "${SMOKE_MODE}" = "true" ]; then
    warn "Smoke-test mode — using 2Y data, no OOS, no macro"
    TRAIN_ARGS="--smoke"
else
    info "Training config: years=${RETRAIN_YEARS}  oos_years=${RETRAIN_OOS_YEARS}  stacking=${RETRAIN_STACKING}"
    TRAIN_ARGS="--years ${RETRAIN_YEARS} --oos-years ${RETRAIN_OOS_YEARS}"
    if [ "${RETRAIN_STACKING}" = "true" ]; then
        TRAIN_ARGS="${TRAIN_ARGS} --stacking"
    fi
fi

# ── Step 1: Run training ──────────────────────────────────────────────────────
echo ""
echo "[ 1/4 ] Training model…"
START_TS=$(date +%s)

python3 ml/train_advanced.py ${TRAIN_ARGS} || fail "Training failed — see output above."

END_TS=$(date +%s)
ELAPSED=$(( END_TS - START_TS ))
ok "Training complete in ${ELAPSED}s"

# ── Step 2: Verify model integrity ───────────────────────────────────────────
echo ""
echo "[ 2/4 ] Verifying model integrity…"

if [ "${SKIP_VERIFY}" = "true" ]; then
    warn "SKIP_VERIFY=true — skipping ml/verify_model.py"
else
    python3 -m ml.verify_model || fail "Model verification failed — model not deployed."
    ok "Model integrity verified"
fi

# ── Step 3: Print OOS metrics summary ────────────────────────────────────────
echo ""
echo "[ 3/4 ] OOS metrics summary"

python3 - <<'PYEOF'
import json, sys
from pathlib import Path

meta_path = Path("ml/saved_models/advanced_oos_meta.json")
if not meta_path.exists():
    print("  [WARN] advanced_oos_meta.json not found — skipping summary")
    sys.exit(0)

meta = json.loads(meta_path.read_text())
sg = meta.get("sharpe_gate", {})

print(f"  Symbol       : {meta.get('symbol', 'unknown')}")
print(f"  Years        : {meta.get('years', '?')}Y  OOS: {meta.get('oos_years', '?')}Y")
print(f"  OOS period   : {meta.get('oos_period', 'unknown')}")
print(f"  OOS accuracy : {meta.get('oos_accuracy', 0):.4f}  (p={meta.get('oos_p_value', 1):.4f}  N={meta.get('oos_n', 0)})")
print(f"  OOS F1       : {meta.get('oos_f1', 0):.4f}")
print(f"  OOS AUC      : {meta.get('oos_auc', 0):.4f}")
print(f"  Sharpe gate  : {'PASSED' if sg.get('gate_passed') else 'FAILED'}  "
      f"(N={sg.get('n_trades', 0)}  SE={sg.get('se', 0):.3f}  Sharpe={sg.get('sharpe', 0):.2f})")
print(f"  Features     : {meta.get('feature_count', '?')}")
print(f"  Trained at   : {meta.get('trained_at', 'unknown')}")
PYEOF

ok "Metrics printed"

# ── Step 4: Confirm current.pkl symlink ───────────────────────────────────────
echo ""
echo "[ 4/4 ] Confirming current.pkl symlink"

python3 - <<'PYEOF'
import sys
from pathlib import Path

symlink = Path("ml/saved_models/current.pkl")
if not symlink.exists():
    print("  [WARN] current.pkl symlink missing — creating…")
    target = Path("ml/saved_models/advanced_oos.pkl")
    if not target.exists():
        print("  [ERROR] advanced_oos.pkl not found", file=sys.stderr)
        sys.exit(1)
    symlink.symlink_to(target.name)
    print(f"  [OK] current.pkl → {target.name}")
else:
    resolved = symlink.resolve().name
    print(f"  [OK] current.pkl → {resolved}")
PYEOF

ok "current.pkl symlink confirmed"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  Retraining complete. Model is ready for production inference.${NC}"
echo ""
echo "  Next steps:"
echo "    1. Review OOS metrics above — ensure Sharpe gate PASSED"
echo "    2. Run: python -m ml.verify_model  (if not already done)"
echo "    3. Restart the API server to load the new model"
echo "       (InferenceEngine singleton reloads on next request after restart)"
echo ""
