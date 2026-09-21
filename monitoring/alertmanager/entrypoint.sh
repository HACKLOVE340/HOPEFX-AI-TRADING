#!/bin/sh
# monitoring/alertmanager/entrypoint.sh
# Decides which notification channels are usable, renders the config, validates
# it, says out loud what it did, and execs alertmanager.
#
# The rendering itself lives in render-config.sh so it can be tested without a
# container. See that file for why substitution uses awk and not `eval`.
set -eu

TMPL=/etc/alertmanager/alertmanager.yml.tmpl
OUT=/tmp/alertmanager.yml
RENDER=/render-config.sh
CHANNELS=/channels.sh

# Sets HOPEFX_AM_{TELEGRAM,EMAIL,PAGERDUTY}_ENABLED. render-config.sh sources
# the same file, so the banner below describes the config that was actually
# written and not a second opinion about it.
# shellcheck source=channels.sh
. "$CHANNELS"

"$RENDER" "$TMPL" "$CHANNELS" > "$OUT"

# ── Validate before exec ─────────────────────────────────────────────────────
#
# The conditional blocks are meant to make an invalid render impossible, but a
# future edit to the template can still break it, and the way that failure
# presented last time was a container restarting every second with the reason
# scrolled off. Check it here and print the rendered file with line numbers, so
# "field X not found in type config.plain" points at something.
if command -v amtool >/dev/null 2>&1; then
    if ! amtool check-config "$OUT" >/dev/null 2>&1; then
        echo "alertmanager: RENDERED CONFIG IS INVALID — refusing to start" >&2
        amtool check-config "$OUT" >&2 || true
        echo "alertmanager: ---- rendered config ----" >&2
        awk '{ printf "%4d  %s\n", NR, $0 }' "$OUT" >&2
        exit 1
    fi
fi

# ── Say what is actually armed ───────────────────────────────────────────────
#
# A monitoring stack that comes up notifying nobody looks identical to one that
# is working right up until the moment it matters.
echo "alertmanager: telegram=${HOPEFX_AM_TELEGRAM_ENABLED:-off} email=${HOPEFX_AM_EMAIL_ENABLED:-off} pagerduty=${HOPEFX_AM_PAGERDUTY_ENABLED:-off}"
if [ -z "${HOPEFX_AM_TELEGRAM_ENABLED}${HOPEFX_AM_EMAIL_ENABLED}${HOPEFX_AM_PAGERDUTY_ENABLED}" ]; then
    echo "alertmanager: WARNING — no notification channel is configured." >&2
    echo "alertmanager:           Alerts will be received, grouped, and DROPPED." >&2
    echo "alertmanager:           Set ALERTMANAGER_SMTP_TO/_HOST, or ALERTMANAGER_TELEGRAM_BOT_TOKEN" >&2
    echo "alertmanager:           plus ALERTMANAGER_TELEGRAM_CHAT_ID, or ALERTMANAGER_PAGERDUTY_KEY." >&2
fi

exec /bin/alertmanager \
    --config.file="$OUT" \
    --storage.path=/alertmanager \
    --web.listen-address=:9093 \
    --cluster.listen-address= \
    "$@"
