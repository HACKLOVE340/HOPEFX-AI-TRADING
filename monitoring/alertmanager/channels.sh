# monitoring/alertmanager/channels.sh
# Decides which notification channels are usable, from the ALERTMANAGER_* env.
# Sourced (not executed) by render-config.sh and entrypoint.sh, so the rendered
# config and the startup banner can never disagree about what is armed.
#
# Sets, to "1" or empty:
#   HOPEFX_AM_TELEGRAM_ENABLED
#   HOPEFX_AM_EMAIL_ENABLED
#   HOPEFX_AM_PAGERDUTY_ENABLED
#
# Why a channel is dropped rather than declared empty: alertmanager treats a
# blank credential as a hard startup error, not a warning. Verified against
# prom/alertmanager v0.27.0:
#
#   bot_token: ''     → missing bot_token or bot_token_file on telegram_config
#   chat_id: 0        → missing chat_id on telegram_config
#   to: ''            → missing to address in email config
#   routing_key: ''   → missing service or routing key in PagerDuty config
#
# A receiver with no integrations at all, by contrast, is valid. So an
# unconfigured channel must be absent, not blank.
#
# Written with if/then rather than `[ ... ] && VAR=1`: under `set -e` a failing
# test as the last command of a function or script aborts the caller.

HOPEFX_AM_TELEGRAM_ENABLED=""
HOPEFX_AM_EMAIL_ENABLED=""
HOPEFX_AM_PAGERDUTY_ENABLED=""

if [ -n "${ALERTMANAGER_TELEGRAM_BOT_TOKEN:-}" ]; then
    if [ -n "${ALERTMANAGER_TELEGRAM_CHAT_ID:-}" ] && [ "${ALERTMANAGER_TELEGRAM_CHAT_ID}" != "0" ]; then
        HOPEFX_AM_TELEGRAM_ENABLED=1
    else
        echo "alertmanager: TELEGRAM DISABLED — bot token is set but ALERTMANAGER_TELEGRAM_CHAT_ID is missing or 0" >&2
    fi
fi

# Both are required: an SMTP relay with no recipient sends nothing, and a
# recipient with no relay is the compose default (localhost:587) pointing at a
# port nothing listens on inside the container.
if [ -n "${ALERTMANAGER_SMTP_TO:-}" ] && [ -n "${ALERTMANAGER_SMTP_HOST:-}" ]; then
    HOPEFX_AM_EMAIL_ENABLED=1
elif [ -n "${ALERTMANAGER_SMTP_TO:-}" ]; then
    echo "alertmanager: EMAIL DISABLED — ALERTMANAGER_SMTP_TO is set but ALERTMANAGER_SMTP_HOST is empty" >&2
fi

if [ -n "${ALERTMANAGER_PAGERDUTY_KEY:-}" ]; then
    HOPEFX_AM_PAGERDUTY_ENABLED=1
fi

export HOPEFX_AM_TELEGRAM_ENABLED HOPEFX_AM_EMAIL_ENABLED HOPEFX_AM_PAGERDUTY_ENABLED
