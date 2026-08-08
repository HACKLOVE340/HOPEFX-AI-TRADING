#!/usr/bin/env bash
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
#
# scripts/deploy.sh — pull and restart a server checkout, safely.
#
# WHY THIS EXISTS
# ---------------
# The production checkout accumulated uncommitted edits to 39 tracked files and
# refused its own deploy:
#
#     error: Your local changes to the following files would be overwritten by
#     merge: .env.example  CLAUDE.md  api/trading.py  …
#
# `git pull` is the wrong tool for a server. It merges, so it fails whenever the
# working tree has drifted, and drift on a box nobody is supposed to edit is
# invisible until it blocks a release. This script makes the checkout match the
# remote exactly — `fetch` + `reset --hard` — so the deployed code is always a
# commit you can name.
#
# WHAT IT WILL NOT DO
# -------------------
# It never runs `git clean`. In this repository `.gitignore` covers `.env`,
# `*.db`, `*.sqlite`, `WORDMAP.json`, `prop_firm_mode.json` and `logs/` — a
# `git clean -fdx` would delete the production database, the live credentials
# and the trading config in one command. `reset --hard` only touches files git
# already tracks, which is exactly the blast radius wanted here.
#
# It also never discards silently: local modifications are written to a patch
# file under $BACKUP_DIR before anything is reset, so a wrong guess is always
# recoverable. Restore with `git apply -3` — the three-way form, because a plain
# `git apply` refuses whenever the incoming commits touched the same lines, which
# is precisely the case you need it for. The `-3` form merges instead and leaves
# ordinary conflict markers to resolve.
#
# USAGE
#   ./scripts/deploy.sh                      # deploy origin/main
#   ./scripts/deploy.sh --ref v1.2.3         # deploy a tag or commit
#   ./scripts/deploy.sh --service hopefx     # systemd unit to restart
#   ./scripts/deploy.sh --dry-run            # show what would happen
#   ./scripts/deploy.sh --no-restart         # pull + migrate only
#
# ENVIRONMENT
#   HOPEFX_SERVICE     systemd unit name (default: autodetected, else none)
#   HOPEFX_HEALTH_URL  health endpoint    (default: http://127.0.0.1:8000/api/health/live)
#   HOPEFX_BACKUP_DIR  patch destination  (default: /var/backups/hopefx)

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REF="origin/main"
SERVICE="${HOPEFX_SERVICE:-}"
HEALTH_URL="${HOPEFX_HEALTH_URL:-http://127.0.0.1:8000/api/health/live}"
BACKUP_DIR="${HOPEFX_BACKUP_DIR:-/var/backups/hopefx}"
DRY_RUN=0
DO_RESTART=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)        REF="$2"; shift 2 ;;
    --service)    SERVICE="$2"; shift 2 ;;
    --health-url) HEALTH_URL="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --no-restart) DO_RESTART=0; shift ;;
    -h|--help)    sed -n '2,45p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m  %s\n' "$*" >&2; exit 1; }
run()  { if [[ $DRY_RUN -eq 1 ]]; then printf '   [dry-run] %s\n' "$*"; else "$@"; fi; }

trap 'die "deploy failed at line $LINENO — the service was NOT left half-updated if the failure came before the restart step; check the output above"' ERR

# ── Preflight ─────────────────────────────────────────────────────────────────

command -v git >/dev/null || die "git not found"
git rev-parse --git-dir >/dev/null 2>&1 || die "$REPO_ROOT is not a git repository"

PYTHON="$(command -v python3 || command -v python || true)"
[[ -n "$PYTHON" ]] || die "no python interpreter found"

if [[ -z "$SERVICE" ]] && command -v systemctl >/dev/null 2>&1; then
  # Best-effort autodetect; an explicit --service always wins.
  SERVICE="$(systemctl list-units --type=service --no-legend --plain 2>/dev/null \
             | awk '$1 ~ /hopefx/ {print $1; exit}' || true)"
fi

log "repo:    $REPO_ROOT"
log "ref:     $REF"
log "service: ${SERVICE:-<none — will not restart>}"
[[ $DRY_RUN -eq 1 ]] && warn "dry run: nothing will be changed"

# ── 1. Preserve anything the working tree is carrying ─────────────────────────
#
# Done before the fetch so a network failure cannot leave us having discarded
# something we never backed up.

CURRENT_SHA="$(git rev-parse HEAD)"
STAMP="$(date +%Y%m%d-%H%M%S)"

if ! git diff --quiet || ! git diff --cached --quiet; then
  run mkdir -p "$BACKUP_DIR"
  PATCH="$BACKUP_DIR/local-changes-$STAMP.patch"
  warn "working tree has local modifications:"
  git status --porcelain | sed 's/^/      /'
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '   [dry-run] would save them to %s\n' "$PATCH"
  else
    # HEAD covers staged and unstaged together; --binary so it round-trips, and
    # the index lines it carries are what lets `git apply -3` merge later.
    git diff --binary HEAD > "$PATCH"
    log "local changes saved to $PATCH"
    log "  restore with: git apply -3 '$PATCH'   (-3 merges; plain apply refuses when upstream touched the same lines)"
  fi
else
  log "working tree clean"
fi

UNTRACKED="$(git ls-files --others --exclude-standard | head -20)"
if [[ -n "$UNTRACKED" ]]; then
  # Left alone on purpose: reset --hard does not touch untracked files, and
  # this is where .env, the sqlite database and WORDMAP.json live.
  log "untracked files present and will be left untouched:"
  echo "$UNTRACKED" | sed 's/^/      /'
fi

# ── 2. Fetch and reset ────────────────────────────────────────────────────────

log "fetching"
run git fetch --prune origin

TARGET_SHA="$(git rev-parse --verify "${REF}^{commit}" 2>/dev/null)" \
  || die "cannot resolve ref '$REF' — is it fetched?"

if [[ "$CURRENT_SHA" == "$TARGET_SHA" ]]; then
  log "already at $(git log --oneline -1 "$TARGET_SHA")"
else
  log "moving $(git rev-parse --short "$CURRENT_SHA") -> $(git rev-parse --short "$TARGET_SHA")"
  git --no-pager log --oneline "$CURRENT_SHA..$TARGET_SHA" 2>/dev/null | sed 's/^/      /' || true
  run git reset --hard "$TARGET_SHA"
fi

# Record where we came from, for the rollback line printed on a failed health
# check. Skipped under --dry-run: a dry run that writes a file is not a dry run.
if [[ $DRY_RUN -eq 0 ]]; then
  mkdir -p "$BACKUP_DIR" 2>/dev/null || true
  echo "$CURRENT_SHA" > "$BACKUP_DIR/previous-sha-$STAMP.txt" 2>/dev/null || true
fi

# ── 3. Dependencies ───────────────────────────────────────────────────────────
#
# Only when the manifest actually changed — a pip install on every deploy is
# minutes of downtime for nothing.

if [[ "$CURRENT_SHA" != "$TARGET_SHA" ]] \
   && ! git diff --quiet "$CURRENT_SHA" "$TARGET_SHA" -- requirements.txt 2>/dev/null; then
  log "requirements.txt changed — installing"
  run "$PYTHON" -m pip install -r requirements.txt --quiet
else
  log "requirements.txt unchanged — skipping pip"
fi

# ── 4. Migrations, before the restart ─────────────────────────────────────────
#
# Deliberately before. The new code expects the new schema; restarting first
# would run it against the old one.

if [[ -f alembic.ini ]]; then
  log "applying database migrations"
  run "$PYTHON" -m alembic -c alembic.ini upgrade head
else
  warn "no alembic.ini — skipping migrations"
fi

# ── 5. Restart ────────────────────────────────────────────────────────────────

if [[ $DO_RESTART -eq 0 ]]; then
  log "--no-restart given; stopping here"
  exit 0
fi

if [[ -z "$SERVICE" ]]; then
  warn "no service to restart — restart the app yourself, the code and schema are updated"
  exit 0
fi

log "restarting $SERVICE"
run systemctl restart "$SERVICE"

# ── 6. Prove it came back ─────────────────────────────────────────────────────
#
# A deploy that does not check is a deploy that reports success while the
# service crashloops.

if [[ $DRY_RUN -eq 1 ]]; then
  log "[dry-run] would poll $HEALTH_URL"
  exit 0
fi

log "waiting for $HEALTH_URL"
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
    log "healthy after ${attempt}s"
    log "deployed $(git log --oneline -1)"
    exit 0
  fi
  sleep 1
done

warn "service did not become healthy within 30s"
warn "logs:      journalctl -u $SERVICE -n 50 --no-pager"
warn "roll back: git reset --hard $CURRENT_SHA && systemctl restart $SERVICE"
warn "           (migrations are NOT rolled back — check alembic downgrade if the schema is the problem)"
exit 1
