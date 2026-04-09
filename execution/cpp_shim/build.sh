#!/usr/bin/env bash
# execution/cpp_shim/build.sh
# ============================
# Build the HOPEFX C++ execution shim natively.
#
# Usage:
#   ./build.sh              # Release build (default)
#   ./build.sh --debug      # Debug build with sanitizers
#   ./build.sh --clean      # Remove build directory first
#   ./build.sh --docker     # Build via Docker (no local toolchain needed)
#
# Prerequisites (native build):
#   apt-get install -y build-essential cmake pkg-config libzmq3-dev
#
# Output:
#   build/hopefx_shim       — compiled binary
#
# After building, start the shim:
#   ./build/hopefx_shim &
#
# Then enable it in .env:
#   CPP_SHIM_ENABLED=true

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"
BUILD_TYPE="Release"
CLEAN=false
USE_DOCKER=false

# ── Parse arguments ───────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --debug)   BUILD_TYPE="Debug" ;;
    --clean)   CLEAN=true ;;
    --docker)  USE_DOCKER=true ;;
    --help|-h)
      sed -n '2,20p' "$0" | sed 's/^# //'
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg  (use --help for usage)" >&2
      exit 1
      ;;
  esac
done

# ── Docker build path ─────────────────────────────────────────────────────────
if [[ "$USE_DOCKER" == "true" ]]; then
  echo "Building via Docker..."
  docker build -t hopefx-shim:latest "$SCRIPT_DIR"
  # Extract binary from image
  mkdir -p "$BUILD_DIR"
  docker create --name hopefx-shim-extract hopefx-shim:latest
  docker cp hopefx-shim-extract:/app/hopefx_shim "$BUILD_DIR/hopefx_shim"
  docker rm hopefx-shim-extract
  echo "Binary extracted to: $BUILD_DIR/hopefx_shim"
  exit 0
fi

# ── Dependency checks ─────────────────────────────────────────────────────────
check_dep() {
  if ! command -v "$1" &>/dev/null; then
    echo "ERROR: '$1' not found. Install with: $2" >&2
    exit 1
  fi
}

check_dep cmake  "apt-get install -y cmake"
check_dep g++    "apt-get install -y build-essential"
check_dep pkg-config "apt-get install -y pkg-config"

if ! pkg-config --exists libzmq 2>/dev/null; then
  echo "ERROR: libzmq not found. Install with: apt-get install -y libzmq3-dev" >&2
  exit 1
fi

ZMQ_VERSION=$(pkg-config --modversion libzmq 2>/dev/null || echo "unknown")
CMAKE_VERSION=$(cmake --version | head -1)
GXX_VERSION=$(g++ --version | head -1)

echo "Build configuration:"
echo "  Type:    $BUILD_TYPE"
echo "  CMake:   $CMAKE_VERSION"
echo "  g++:     $GXX_VERSION"
echo "  libzmq:  $ZMQ_VERSION"
echo "  Output:  $BUILD_DIR/hopefx_shim"
echo ""

# ── Clean ─────────────────────────────────────────────────────────────────────
if [[ "$CLEAN" == "true" ]] && [[ -d "$BUILD_DIR" ]]; then
  echo "Removing existing build directory..."
  rm -rf "$BUILD_DIR"
fi

# ── Configure ─────────────────────────────────────────────────────────────────
echo "Configuring..."
cmake -B "$BUILD_DIR" \
  -S "$SCRIPT_DIR" \
  -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
  ${BUILD_TYPE:+-DCMAKE_BUILD_TYPE="$BUILD_TYPE"}

# ── Build ─────────────────────────────────────────────────────────────────────
NPROC=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
echo "Building with $NPROC parallel jobs..."
cmake --build "$BUILD_DIR" --parallel "$NPROC"

# ── Verify ────────────────────────────────────────────────────────────────────
BINARY="$BUILD_DIR/hopefx_shim"
if [[ ! -f "$BINARY" ]]; then
  echo "ERROR: Build succeeded but binary not found at $BINARY" >&2
  exit 1
fi

SIZE=$(du -sh "$BINARY" | cut -f1)
echo ""
echo "Build complete: $BINARY ($SIZE)"
echo ""
echo "To start the shim:"
echo "  $BINARY &"
echo ""
echo "To enable in .env:"
echo "  CPP_SHIM_ENABLED=true"
