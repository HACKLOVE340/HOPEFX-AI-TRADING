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

## Enable in .env

```
CPP_SHIM_ENABLED=true
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
