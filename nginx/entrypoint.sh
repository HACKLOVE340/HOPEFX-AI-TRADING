#!/bin/sh
# nginx/entrypoint.sh
# Substitutes ${HOPEFX_DOMAIN} in nginx.conf before starting nginx.
# Required env vars:
#   HOPEFX_DOMAIN  — e.g. hopefx.io  (no protocol, no trailing slash)

set -e

: "${HOPEFX_DOMAIN:?HOPEFX_DOMAIN env var must be set (e.g. hopefx.io)}"

# Replace ${HOPEFX_DOMAIN} placeholders in the template and write to the
# active nginx config location.
# shellcheck disable=SC2016  # single quotes intentional: envsubst variable list, not shell expansion
envsubst '${HOPEFX_DOMAIN}' \
  < /etc/nginx/nginx.conf.template \
  > /etc/nginx/nginx.conf

echo "[entrypoint] nginx.conf generated for domain: ${HOPEFX_DOMAIN}"

exec nginx -g "daemon off;"
