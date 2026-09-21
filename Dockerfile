# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Build the React frontend
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /build/frontend

# Install deps first (layer-cached unless package.json changes)
COPY frontend/package.json frontend/package-lock.json ./
# `--legacy-peer-deps` is a WORKAROUND for an npm crash, not a preference.
#
# npm's arborist loads the OPTIONAL peer sets of packages named in the lockfile
# even for `ci`, which resolves nothing and should need no registry at all. On
# 2026-09-18 that walk reached `@vitest/browser-playwright@5.0.1` — an optional
# peer of the locked `vitest@4.1.11` — which peers on `vitest@*`, resolving to
# the newly published vitest 5, whose own `@vitejs/devtools-*@^0.7.5` peers sent
# it into a recursion that dereferences null:
#
#     npm error Cannot read properties of null (reading 'edgesOut')
#     at #loadPeerSet (@npmcli/arborist/lib/arborist/build-ideal-tree.js:1289)
#
# Reproduced on npm 10.9.7 and on npm 10.8.2 — the version node:20-alpine above
# ships — so this stage could not build at all, and nothing in this repository
# had changed. The lockfile is sound: with this flag `npm ci` installs 738
# packages at 0 version mismatches and 0 packages absent from the lock, which is
# exactly the locked tree.
#
# Remove the flag once npm ships the fix, and let
# tests/unit/test_frontend_lockfile_installs_cleanly.py prove it is safe to.
RUN npm ci --legacy-peer-deps

# Frontend base URLs. Vite inlines VITE_* at build time, so these have to be
# present here — setting them in .env only affects the running container, which
# never sees them. `.env.example` documented VITE_API_URL / VITE_WS_URL as the
# way to point the UI at a separate API domain, but nothing passed them into
# this stage, so setting them had no effect at all.
#
# Left empty they stay empty, and lib/utils.ts treats empty as "not configured"
# and falls back to same-origin — which is what the bundled deployment wants.
ARG VITE_API_URL=""
ARG VITE_WS_URL=""
ARG VITE_NUCLEAR_WS_URL=""
ENV VITE_API_URL=$VITE_API_URL \
    VITE_WS_URL=$VITE_WS_URL \
    VITE_NUCLEAR_WS_URL=$VITE_NUCLEAR_WS_URL

# Copy source and build — output lands in /build/static (vite outDir: '../static')
COPY frontend/ ./
RUN npm run build


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Python runtime
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# System deps:
#   gcc/g++         — compile C-extension wheels (e.g. quickfix, psycopg2)
#   libquickfix-dev — FIX protocol C-extension
#   libpq-dev       — psycopg2 PostgreSQL driver
#   curl            — HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libquickfix-dev \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (cached unless requirements files change).
# requirements-cpu.txt MUST be installed first: sentence-transformers (in
# requirements.txt) pulls torch transitively, and a bare `pip install -r
# requirements.txt` resolves the default CUDA build (torch + ~5GB of nvidia-*
# wheels) — this container runs on CPU-only VPS hosts. Installing the CPU
# wheel first satisfies that transitive dependency so the second install
# finds torch already present and skips the CUDA wheels entirely.
COPY requirements-cpu.txt requirements.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu -r requirements-cpu.txt \
    && pip install --no-cache-dir -r requirements.txt \
    # Verify critical runtime deps are present — fail the build if missing
    && python -c "import uvicorn; import aiohttp; print('uvicorn', uvicorn.__version__, '| aiohttp', aiohttp.__version__)"

# Copy application source
COPY . .

# Copy the compiled frontend bundle from stage 1
COPY --from=frontend-builder /build/static ./static

# Create runtime directories and a non-root user
RUN mkdir -p logs data credentials state fix_store fix_logs \
    && useradd -m -u 1001 hopefx \
    && chown -R hopefx:hopefx /app \
    && chmod +x scripts/preflight.sh

# Drop root before the process starts
USER hopefx

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production
ENV API_PORT=8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${API_PORT}/api/health/live || exit 1

# Run pre-flight checks then start the API server.
# Set SKIP_TESTS=true or SKIP_MIGRATIONS=true in .env to speed up restarts.
CMD ["bash", "-c", "scripts/preflight.sh && python app.py"]
