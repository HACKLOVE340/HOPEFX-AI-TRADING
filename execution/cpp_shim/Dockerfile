# execution/cpp_shim/Dockerfile
# ================================
# Builds the HOPEFX C++ execution shim in a minimal container.
#
# Multi-stage build:
#   Stage 1 (builder) — compiles hopefx_shim with full toolchain
#   Stage 2 (runtime) — copies only the binary + libzmq into a slim image
#
# The runtime image is ~50 MB vs ~800 MB for the full build image.

# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM debian:bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    pkg-config \
    libzmq3-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY hopefx_shim.cpp CMakeLists.txt ./

RUN cmake -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_EXE_LINKER_FLAGS="-static-libgcc -static-libstdc++" \
    && cmake --build build --parallel "$(nproc)" \
    && strip build/hopefx_shim

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -m -u 1001 hopefx

WORKDIR /app/shim
COPY --from=builder /build/build/hopefx_shim ./hopefx_shim
RUN chown hopefx:hopefx hopefx_shim && chmod +x hopefx_shim

USER hopefx

# ZMQ ports
EXPOSE 6555 6556

ENV ZMQ_CMD_PORT=6555
ENV ZMQ_RESP_PORT=6556
ENV FIX_HOST=127.0.0.1
ENV FIX_PORT=9876
ENV FIX_SENDER_COMP_ID=HOPEFX
ENV FIX_TARGET_COMP_ID=CME
ENV CPU_AFFINITY_CORE=-1
ENV LATENCY_WARN_US=500
ENV BUSY_POLL_US=50

ENTRYPOINT ["/app/shim/hopefx_shim"]
