#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# HOPEFX — diagnose "the wrong landing page is being served"
# ---------------------------------------------------------------------------
# Run this ON THE VPS, from the repo root:
#
#     bash deployments/diagnose_served_page.sh
#
# WHY THIS EXISTS
# The public site was serving a page whose copy ("A cleaner landing page for
# faster, calmer trading", "Markets monitored", "Decision speed",
# "Risk visibility") does not exist anywhere in this repository — not in the
# working tree, not in any commit, on any branch. It was therefore never built
# from frontend/src/pages/LandingPage.tsx; something in front of, or instead
# of, the app container was answering the request.
#
# The real landing page is frontend/src/pages/LandingPage.tsx, mounted at "/"
# in frontend/src/App.tsx, built by Vite into ./static (vite outDir '../static')
# and baked into the image by the Dockerfile's frontend-builder stage. Its
# fingerprints are:
#
#     <title>HOPEFX — AI-Powered Gold & Forex Trading Platform</title>
#     "HOPEFX combines machine learning, macro data feeds, and automated risk
#      management"                                    (hero sub-copy)
#     "institutional-grade AI"                        (hero headline)
#
# This script compares three layers and tells you which one is lying:
#
#     1. the app container itself      (127.0.0.1:8000)
#     2. the image's baked-in static/  (docker compose exec)
#     3. the public URL                (https://$DOMAIN)
#
# It is READ-ONLY. It changes nothing; it prints the fix for whatever it finds.
# ---------------------------------------------------------------------------
set -uo pipefail

DOMAIN="${HOPEFX_DOMAIN:-hopefx.site}"
APP_LOCAL="http://127.0.0.1:8000"

# Marker that only the real Vite-built landing page contains.
GOOD_COPY='HOPEFX combines machine learning'
# Markers of the stray page that is not in this repo.
BAD_COPY='cleaner landing page'
BAD_COPY2='Markets monitored'

pass() { printf '  \033[32m[OK]\033[0m   %s\n' "$1"; }
warn() { printf '  \033[33m[WARN]\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m[BAD]\033[0m  %s\n' "$1"; }
info() { printf '         %s\n' "$1"; }
hdr()  { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

title_of() { grep -o '<title>[^<]*</title>' "$1" 2>/dev/null | head -1; }

classify() {
    # classify <file> <label>
    f=$1 label=$2
    if [ ! -s "$f" ]; then
        bad "$label: no response / empty body"
        return 1
    fi
    t=$(title_of "$f")
    info "$label title: ${t:-<none>}"
    if grep -qF "$GOOD_COPY" "$f"; then
        pass "$label: serving the REAL landing page (hero copy found inline)"
        return 0
    fi
    if grep -qF "$BAD_COPY" "$f" || grep -qF "$BAD_COPY2" "$f"; then
        bad "$label: serving the STRAY page (copy that is not in this repo)"
        return 2
    fi
    case "$t" in
        *"AI-Powered Gold"*)
            # Correct shell; hero copy lives in the JS chunk, not index.html.
            pass "$label: serving the real app shell (SPA — copy is in /assets/LandingPage-*.js)"
            return 0 ;;
        *GodMode*)
            bad "$label: serving dashboard/dist (legacy GodMode) — static/ is MISSING in the container"
            return 3 ;;
        *"Build Required"*)
            bad "$label: serving the 'Frontend Build Required' placeholder — static/ is MISSING"
            return 4 ;;
        *)
            bad "$label: unknown page — not produced by this repo"
            return 5 ;;
    esac
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# ── 1. what the app container serves directly ────────────────────────────────
hdr "1. App container, bypassing every proxy ($APP_LOCAL/)"
curl -sS --max-time 15 -o "$TMP/app.html" -w '  HTTP %{http_code}\n' "$APP_LOCAL/" 2>&1 || true
classify "$TMP/app.html" "app:8000"
APP_RC=$?

# ── 2. what is actually baked into the image ─────────────────────────────────
hdr "2. static/ inside the running container"
if command -v docker >/dev/null 2>&1; then
    docker compose exec -T app sh -c '
        if [ -f static/index.html ]; then
            echo "  static/index.html present ($(wc -c < static/index.html) bytes)"
            grep -o "<title>[^<]*</title>" static/index.html | head -1 | sed "s/^/  /"
            n=$(ls static/assets/LandingPage-*.js 2>/dev/null | wc -l)
            echo "  LandingPage chunk(s): $n"
            grep -l "HOPEFX combines machine learning" static/assets/*.js 2>/dev/null | head -2 | sed "s/^/  /"
        else
            echo "  static/index.html is MISSING — the frontend-builder stage did not land"
            ls -la static 2>/dev/null | head -5 | sed "s/^/  /"
        fi
    ' 2>&1 | sed 's/^/  /' || warn "could not exec into the app container (is the stack up?)"
else
    warn "docker not on PATH — skipping container inspection"
fi

# ── 3. what the public URL serves ────────────────────────────────────────────
hdr "3. Public URL (https://$DOMAIN/)"
curl -sS --max-time 20 -o "$TMP/pub.html" -w '  HTTP %{http_code}  server=%{remote_ip}\n' \
    "https://$DOMAIN/" 2>&1 || true
classify "$TMP/pub.html" "public"
PUB_RC=$?

# ── 4. the proxy in front ────────────────────────────────────────────────────
hdr "4. Reverse proxy"
for svc in caddy nginx apache2; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        info "$svc is ACTIVE"
    fi
done
if command -v ss >/dev/null 2>&1; then
    info "listeners on :80 / :443 —"
    ss -ltnp 2>/dev/null | grep -E ':80 |:443 ' | sed 's/^/           /' || info "  (none)"
fi

CADDYFILE=/etc/caddy/Caddyfile
hdr "5. $CADDYFILE"
if [ ! -f "$CADDYFILE" ]; then
    warn "not present — Caddy is either unconfigured or not the proxy here"
else
    sed 's/^/  /' "$CADDYFILE"
    if grep -qE '^[[:space:]]*(root|file_server)' "$CADDYFILE"; then
        bad "This Caddyfile serves files from DISK (root/file_server), not the app."
        info "That is the classic cause of a stray landing page: Caddy answers from"
        info "a directory on the host and never touches the container."
    fi
    if ! grep -q "$DOMAIN" "$CADDYFILE"; then
        bad "$DOMAIN has no site block — TLS/routing for it is undefined."
    fi
fi

# ── 6. stray HTML on the host containing the wrong copy ──────────────────────
hdr "6. Stray HTML files on the host carrying the non-repo copy"
FOUND=0
for d in /var/www /usr/share/caddy /usr/share/nginx /srv /opt; do
    [ -d "$d" ] || continue
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        bad "$f"
        FOUND=1
    done <<EOF
$(grep -rlF --include='*.html' -e "$BAD_COPY" -e "$BAD_COPY2" "$d" 2>/dev/null | head -10)
EOF
done
[ "$FOUND" -eq 0 ] && pass "none found under /var/www /usr/share/caddy /usr/share/nginx /srv /opt"

# ── Verdict ──────────────────────────────────────────────────────────────────
hdr "VERDICT"
if [ "$APP_RC" -eq 1 ]; then
    bad "The app container did not answer on $APP_LOCAL at all."
    info "Nothing about the landing page can be concluded until it is up. Check:"
    info "  docker compose ps"
    info "  docker compose logs --tail=50 app"
elif [ "$APP_RC" -eq 0 ] && [ "$PUB_RC" -eq 0 ]; then
    pass "Both layers serve the real landing page. If your BROWSER still shows the"
    info "old one, it is the PWA service worker cache. Hard-fix in the browser:"
    info "  DevTools -> Application -> Service Workers -> Unregister, then"
    info "  Application -> Storage -> Clear site data, then reload."
elif [ "$APP_RC" -eq 0 ] && [ "$PUB_RC" -ne 0 ]
then
    bad "The app is correct; the PROXY is serving something else."
    info "Fix: make Caddy proxy the app and nothing else. Write $CADDYFILE as:"
    cat <<EOF

    $DOMAIN, www.$DOMAIN {
        encode gzip zstd
        reverse_proxy 127.0.0.1:8000
    }

EOF
    info "Then: sudo caddy validate --config $CADDYFILE && sudo systemctl reload caddy"
    info "Note 127.0.0.1:8000, not app:8000 — Caddy runs on the HOST, not in the"
    info "compose network, so the Docker service name does not resolve."
else
    bad "The APP container is not serving the real page."
    info "Rebuild so the Vite output is baked in fresh:"
    info "  docker compose build --no-cache app && docker compose up -d app"
    info "The Dockerfile's frontend-builder stage runs 'npm run build' and copies"
    info "/build/static -> /app/static. If static/index.html is absent the app"
    info "falls back to dashboard/dist (GodMode) and then to a build placeholder"
    info "(see core/page_routes.py)."
fi
echo
