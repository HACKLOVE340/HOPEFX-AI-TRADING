#!/usr/bin/env bash
# run_mutation_tests.sh — Run mutmut against trading-critical modules.
#
# Usage:
#   ./scripts/run_mutation_tests.sh [--module <path>] [--ci]
#
# Options:
#   --module <path>   Mutate a single module (default: all configured modules)
#   --ci              Exit non-zero if any mutants survive (for CI gates)
#
# Output:
#   - Prints surviving mutant count per module
#   - Writes mutmut HTML report to .mutmut-cache/report.html
#
# Prerequisites:
#   pip install mutmut
#   Tests must pass cleanly before running mutation testing.

set -euo pipefail

MODULES=(
    "core/signal_engine.py"
    "execution/engine.py"
    "backtesting/enhanced_engine.py"
    "core/startup_factories.py"
    "risk/manager.py"
    "kill_switch.py"
)

TEST_CMD="python -m pytest tests/unit/test_property_based.py tests/unit/test_concurrency.py tests/unit/test_chaos.py -x -q --timeout=30"
CI_MODE=false
SINGLE_MODULE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --module) SINGLE_MODULE="$2"; shift 2 ;;
        --ci)     CI_MODE=true; shift ;;
        *)        echo "Unknown argument: $1"; exit 1 ;;
    esac
done

if [[ -n "$SINGLE_MODULE" ]]; then
    MODULES=("$SINGLE_MODULE")
fi

echo "=== Mutation Testing ==="
echo "Test command: $TEST_CMD"
echo ""

TOTAL_SURVIVORS=0

for module in "${MODULES[@]}"; do
    echo "--- Mutating: $module ---"
    mutmut run \
        --paths-to-mutate "$module" \
        --runner "$TEST_CMD" \
        --no-progress 2>/dev/null || true

    survivors=$(mutmut results 2>/dev/null | grep -c "^[0-9]" || echo "0")
    echo "  Survivors: $survivors"
    TOTAL_SURVIVORS=$((TOTAL_SURVIVORS + survivors))

    if [[ "$survivors" -gt 0 ]]; then
        echo "  Surviving mutant IDs:"
        mutmut results 2>/dev/null | grep "^[0-9]" | awk '{print "    mutmut show " $1}' || true
    fi
    echo ""
done

echo "=== Summary ==="
echo "Total surviving mutants: $TOTAL_SURVIVORS"

if [[ "$CI_MODE" == "true" && "$TOTAL_SURVIVORS" -gt 0 ]]; then
    echo "FAIL: $TOTAL_SURVIVORS mutants survived. Add tests to kill them."
    echo "Run 'mutmut show <id>' to inspect each survivor."
    exit 1
fi

echo "Done."
