#!/bin/bash
# HOPEFX-AI-TRADING — SessionStart hook for Claude Code on the web.
#
# Why this exists
# ---------------
# A fresh remote container clones the repo but installs nothing. Running the test
# suite in that state produced ~360 failures and ~82 collection errors that
# looked like real defects and were not: every missing module
# (prometheus-client, matplotlib, pydantic-settings, lightgbm, xgboost,
# argon2-cffi, aiosqlite, fakeredis, pyotp, python-dotenv, strawberry-graphql)
# is already declared in requirements-ci.txt. CI installs it; a web session did
# not, so a suite that is green in CI looked broken here.
#
# One example of how misleading that was: with the ML routers unable to import,
# their routes never registered, so test_auth_coverage_ext's whitelist check
# reported stale entries — an "auth gap" that was really a missing wheel.
#
# Why a virtualenv rather than the system Python
# ---------------------------------------------
# This image's pip, setuptools and wheel are all Debian-packaged with no RECORD
# file, so `pip install --upgrade pip` dies with "Cannot uninstall pip 24.0" and
# three requirements (ta, crcmod, ed25519-blake2b) fail to build against the
# Debian setuptools with `AttributeError: install_layout`. A venv gets its own
# pip/setuptools/wheel and builds all of them cleanly. .venv/ is already in
# .gitignore.
#
# Kept synchronous so dependencies are guaranteed present before the agent runs
# anything. Switch to async mode if session-start latency matters more.
set -euo pipefail

# Local machines have their own environment; only provision the remote one.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  echo "session-start: not a remote session — skipping provisioning"
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

VENV=".venv"

# Reused across sessions when the container image is cached, so this is usually
# a no-op after the first run.
if [ ! -x "$VENV/bin/python" ]; then
  echo "session-start: creating $VENV"
  python3 -m venv "$VENV"
fi

echo "session-start: installing Python dependencies (requirements-ci.txt)"
"$VENV/bin/python" -m pip install --quiet --upgrade pip setuptools wheel
# requirements-ci.txt is what CI installs, so a green suite here means the same
# thing it means in CI. It also carries pytest, pytest-asyncio, pytest-timeout,
# pytest-cov, httpx and ruff, and pulls no torch/tensorflow, so it stays quick.
#
# Non-fatal: a single unbuildable wheel must not leave the session with no
# environment at all. Failures are reported and the test-critical subset is
# installed as a floor, which is far better than exiting here.
if ! "$VENV/bin/python" -m pip install --retries 3 --timeout 60 -r requirements-ci.txt; then
  echo "session-start: WARNING — full requirements-ci.txt install failed."
  echo "session-start: installing the test-critical subset so the suite can still run."
  "$VENV/bin/python" -m pip install --quiet --retries 3 --timeout 60 \
    fastapi uvicorn pydantic pydantic-settings sqlalchemy alembic \
    pytest pytest-asyncio pytest-timeout pytest-cov httpx ruff \
    pyjwt bcrypt argon2-cffi email-validator python-multipart \
    redis fakeredis prometheus-client python-dotenv pyotp \
    pandas numpy aiosqlite || true
fi

# pre-commit is NOT in requirements-ci.txt — it lives in requirements-dev.txt,
# which nothing here installs. So every remote session started without it, while
# CLAUDE.md calls running the hooks "non-negotiable" before committing and
# forbids `--no-verify`. A gate that is mandated in the strongest language the
# repo has and is not installed is the exact defect `hopefx-dead-controls`
# exists to catch, in the tooling that enforces the rules.
#
# The package install is seconds. `install-hooks` builds the ruff/bandit/
# detect-secrets environments and costs a few minutes on a cold image, but it is
# once per image and it is the difference between the gate being runnable and an
# agent discovering mid-commit that it is not. Non-fatal: a failure here must
# leave the session usable, just without the gate warmed.
echo "session-start: installing pre-commit (the commit gate CLAUDE.md mandates)"
if "$VENV/bin/python" -m pip install --quiet --retries 3 --timeout 60 'pre-commit>=4.1.0,<5.0.0'; then
  "$VENV/bin/python" -m pre_commit install-hooks >/dev/null 2>&1 || \
    echo "session-start: WARNING — pre-commit hook envs not pre-built; first run will build them"
else
  echo "session-start: WARNING — pre-commit install failed; run the hooks manually before committing"
fi

echo "session-start: installing frontend dependencies"
if [ -d frontend ]; then
  # `npm install` rather than `npm ci` so a cached node_modules is reused instead
  # of deleted and refetched every session.
  (cd frontend && npm install --no-audit --no-fund --silent) || \
    echo "session-start: WARNING — frontend install failed; JS tests unavailable"
fi

# Several suites expect a reachable Redis (rate limiting, kill-switch latch, the
# order idempotency store). All fall back gracefully without it, but then the
# fallback paths are what get exercised rather than the real ones.
if command -v redis-server >/dev/null 2>&1; then
  redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes --port 6379
  echo "session-start: redis ready"
else
  echo "session-start: redis-server not installed — suites will use their fallbacks"
fi

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  # Put the venv first on PATH so python/pytest/ruff resolve to it.
  echo "export PATH=\"$(pwd)/$VENV/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
  echo "export VIRTUAL_ENV=\"$(pwd)/$VENV\"" >> "$CLAUDE_ENV_FILE"
  # Imports here are top-level (`import app`, `core.middleware`), so a script run
  # from outside the repo root fails without this.
  echo 'export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}."' >> "$CLAUDE_ENV_FILE"
  # auth/jwt.py raises at import when SECURITY_JWT_SECRET is unset or under 32
  # chars, which blocks collection of most of the suite. Generated per session
  # rather than hard-coded: a fixed secret in a tracked file is exactly what
  # detect-secrets exists to catch, and this value must never reach a real
  # deployment.
  echo "export SECURITY_JWT_SECRET=\"$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')\"" >> "$CLAUDE_ENV_FILE"
  echo 'export APP_ENV="test"' >> "$CLAUDE_ENV_FILE"
  echo "session-start: environment written to CLAUDE_ENV_FILE"
fi

echo "session-start: done"
