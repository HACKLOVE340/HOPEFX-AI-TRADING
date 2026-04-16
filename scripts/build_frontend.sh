#!/usr/bin/env bash
# scripts/build_frontend.sh
# Build the React frontend and output to static/ (served by FastAPI).
#
# Usage:
#   ./scripts/build_frontend.sh           # production build
#   ./scripts/build_frontend.sh --check   # typecheck only, no build
#   ./scripts/build_frontend.sh --clean   # remove static/ then rebuild
#
# Output: static/index.html + static/assets/*
# The static/ directory is gitignored — run this after cloning or when
# frontend source changes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$ROOT/frontend"
OUT_DIR="$ROOT/static"

# ── Argument parsing ──────────────────────────────────────────────────────────
CHECK_ONLY=false
CLEAN=false
for arg in "$@"; do
    case "$arg" in
        --check) CHECK_ONLY=true ;;
        --clean) CLEAN=true ;;
    esac
done

# ── Validate prerequisites ────────────────────────────────────────────────────
if ! command -v node >/dev/null 2>&1; then
    echo "[ERROR] Node.js not found. Install Node.js >=20: https://nodejs.org/" >&2
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "[ERROR] npm not found. Install npm >=10." >&2
    exit 1
fi

NODE_VER=$(node --version | sed 's/v//')
NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 20 ]; then
    echo "[ERROR] Node.js >=20 required (found $NODE_VER)" >&2
    exit 1
fi

if [ ! -f "$FRONTEND_DIR/package.json" ]; then
    echo "[ERROR] frontend/package.json not found at $FRONTEND_DIR" >&2
    exit 1
fi

cd "$FRONTEND_DIR"

# ── Install dependencies ──────────────────────────────────────────────────────
echo "[INFO] Installing frontend dependencies..."
npm install --silent

# ── Typecheck only ────────────────────────────────────────────────────────────
if [ "$CHECK_ONLY" = true ]; then
    echo "[INFO] Running TypeScript typecheck..."
    npm run typecheck
    echo "[INFO] Typecheck passed."
    exit 0
fi

# ── Clean previous build ──────────────────────────────────────────────────────
if [ "$CLEAN" = true ] && [ -d "$OUT_DIR" ]; then
    echo "[INFO] Cleaning $OUT_DIR..."
    rm -rf "$OUT_DIR"
fi

# ── Production build ──────────────────────────────────────────────────────────
echo "[INFO] Building frontend (outDir: $OUT_DIR)..."
npm run build

# ── Verify output ─────────────────────────────────────────────────────────────
if [ ! -f "$OUT_DIR/index.html" ]; then
    echo "[ERROR] Build completed but $OUT_DIR/index.html not found." >&2
    exit 1
fi

ASSET_COUNT=$(ls "$OUT_DIR/assets/" 2>/dev/null | wc -l)
echo "[INFO] Frontend built successfully:"
echo "       Output:  $OUT_DIR"
echo "       Assets:  $ASSET_COUNT files"
echo "       Entry:   $OUT_DIR/index.html"
echo ""
echo "[INFO] The FastAPI server will serve the React SPA at http://localhost:8000/"
