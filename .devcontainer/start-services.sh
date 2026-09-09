#!/usr/bin/env bash
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
#
# Bring the stack up inside a devcontainer / GitHub Codespace.
#
# Why this exists
# ---------------
# `.gitpod/automations.yaml` and `.devcontainer/automations.yaml` define redis,
# backend and frontend services, and AGENTS.md tells you to start them with
# `gitpod automations service start backend`. That is a Gitpod CLI command and
# a Gitpod file format. **GitHub Codespaces reads neither.** It reads
# devcontainer.json and nothing else in that directory.
#
# Codespaces is a supported target — docs/ONBOARDING.md names it and
# vite.config.ts allowlists `.preview.app.github.dev` — so a Codespace would
# build the whole environment and then sit there serving nothing, with no error
# to explain why. On a tablet, where opening a terminal and typing three
# commands is real friction, that is the difference between the app being
# usable and not.
#
# Idempotent: safe to run on every container start, and safe to run by hand.
#
# Deliberately NOT done here: nothing changes port visibility. Codespaces
# forwards ports privately by default, so only you (signed in) can open the
# console. This ships a superadmin account seeded with a generated password —
# making the port public would put that on the open internet. Change it from
# the Ports panel if you ever mean to, as a decision rather than a side effect.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

LOGS="$REPO/logs"
mkdir -p "$LOGS"

say() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33m!\033[0m %s\n' "$*"; }

# ── Redis ────────────────────────────────────────────────────────────────────
say "Redis"
if redis-cli -h 127.0.0.1 ping >/dev/null 2>&1; then
  ok "already listening on 6379"
else
  if ! command -v redis-server >/dev/null 2>&1; then
    warn "redis-server not installed — installing"
    apt-get update -qq && apt-get install -y -qq redis-server >/dev/null 2>&1
  fi
  # No password in dev. The backend's REDIS_URL has no auth, and a server that
  # demands one produces "AUTH called without any password configured", which
  # silently drops EventBus to its local fallback — the kill switch then
  # listens on a bus nothing publishes to.
  nohup redis-server --daemonize no --loglevel warning --bind 127.0.0.1 \
    --maxmemory 256mb --maxmemory-policy allkeys-lru --save "" \
    > "$LOGS/redis.log" 2>&1 &
  for _ in $(seq 1 20); do
    redis-cli -h 127.0.0.1 ping >/dev/null 2>&1 && break
    sleep 0.5
  done
  redis-cli -h 127.0.0.1 ping >/dev/null 2>&1 && ok "started on 6379" || warn "did not come up — see logs/redis.log"
fi

# ── .env and seed users ──────────────────────────────────────────────────────
say "Environment"
if [ -f .env ]; then
  ok ".env present"
else
  python3 scripts/bootstrap_dev.py >/dev/null 2>&1 && ok ".env generated, users seeded" \
    || warn "bootstrap_dev.py failed — run it by hand to see why"
fi

# ── Frontend build ───────────────────────────────────────────────────────────
# The SPA is served by the backend from static/, which is gitignored. Worse:
# the test suite writes a placeholder static/index.html ("HOPEFX test SPA
# shell"), so a stale checkout serves a *blank page* rather than an obvious
# error. Build when the real asset bundle is absent.
say "Frontend"
if [ -d static/assets ] && [ -n "$(ls -A static/assets 2>/dev/null)" ]; then
  ok "static/assets present — skipping build"
else
  warn "static/assets missing (or only the test placeholder) — building"
  ( cd frontend && npm install --prefer-offline --no-audit --no-fund >/dev/null 2>&1 \
      && npm run build >/dev/null 2>&1 ) \
    && ok "built to static/" \
    || warn "build failed — cd frontend && npm run build to see why"
fi

# ── Backend ──────────────────────────────────────────────────────────────────
say "Backend"
if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
  ok "already serving on 8000"
else
  OTEL_ENABLED=false \
  APP_ENV=development \
  REDIS_URL=redis://127.0.0.1:6379/0 \
  REDIS_FORCE_TLS=false \
  REDIS_PASSWORD= \
  IS_FORCE_TLS=false \
  STANDBY_ROLE=primary \
  nohup python3 run.py --mode api > "$LOGS/backend.log" 2>&1 &
  ok "starting — logs/backend.log"
fi

# Startup is deliberately backgrounded inside the app too (app.py yields the
# lifespan immediately and gates data endpoints with 503 until the feeds are
# up), so "port open" is not "ready". Wait for the real thing.
printf '  waiting for startup to finish'
READY=""
for _ in $(seq 1 60); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ 2>/dev/null)" = "200" ]; then
    READY="1"; break
  fi
  printf '.'; sleep 5
done
printf '\n'

if [ -n "$READY" ]; then
  ok "ready — open the forwarded port 8000"
  if [ -f .env ]; then
    printf '\n  Seed accounts (passwords live in .env, never commit them):\n'
    printf '    superadmin@hopefx.io  %s\n' "$(grep -E '^BOOTSTRAP_SUPERADMIN_PASSWORD=' .env | cut -d= -f2-)"
    printf '    trader@hopefx.io      %s\n' "$(grep -E '^BOOTSTRAP_TRADER_PASSWORD=' .env | cut -d= -f2-)"
  fi
else
  warn "not ready after 5 minutes — tail -f logs/backend.log"
fi
printf '\n'
