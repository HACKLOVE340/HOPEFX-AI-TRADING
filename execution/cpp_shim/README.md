# HOPEFX C++ Execution Shim

Low-latency FIX 4.4 execution process. Receives orders from the Python trading engine over ZMQ PUSH and returns fills over ZMQ PULL, bypassing Python's GIL and GC pauses.

## Prerequisites

```bash
apt-get install -y build-essential cmake pkg-config libzmq3-dev
```

## Build

```bash
# Release build (recommended for production)
make

# Or using the build script directly
./build.sh

# Debug build with AddressSanitizer
make debug

# Build via Docker (no local toolchain required)
make docker
```

Output binary: `build/hopefx_shim`

## Run

```bash
# Start in background
./build/hopefx_shim &

# Or via make
make run
```

## Operational Phase Gate

**The shim is a latency optimisation. It must not be enabled before the first trade.**

Required order:
1. **Validate edge** — OOS accuracy ≥ 59.9%, Sharpe gate passed
2. **Paper trade** — ≥ 500 fills, ≥ 30 calendar days via OANDA practice API
3. **Live trade** — ≥ 100 live fills, positive P&L
4. **Optimise latency** — only now enable the C++ shim

Without completing steps 1–3, `CPP_SHIM_ENABLED=true` is silently ignored
and a warning is logged. The gate is enforced in `execution/execution.py`.

## Enable in .env

```
# Step 1-3 must be complete before setting these:
CPP_SHIM_ENABLED=true
LATENCY_OPT_PHASE_UNLOCKED=true   # set only after live trading validated
LIVE_FILL_COUNT=100               # updated by execution engine after each live fill
CPP_SHIM_ZMQ_CMD_ADDR=tcp://127.0.0.1:6555
CPP_SHIM_ZMQ_RESP_ADDR=tcp://127.0.0.1:6556
```

## Stop

```bash
make stop
# or
pkill -f hopefx_shim
```

## Docker Compose

```bash
docker compose -f docker-compose.yml -f docker-compose.lowlatency.yml up cpp-shim
```

## CPU Affinity (low-latency VPS)

Set `CPP_SHIM_CORE` in `.env` to pin the shim to a dedicated CPU core. See `deployment/lowlatency/` for the full low-latency setup.
