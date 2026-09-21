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

# nginx REFUSES TO START when an ssl_certificate file is missing — it is a hard
# configuration error, not a warning. The template points at
# /etc/letsencrypt/live/${HOPEFX_DOMAIN}/, which only exists after certbot has
# issued for this exact domain. On a first deploy it does not, so nginx dies
# immediately with a message about a file, and the visible symptom is a
# container that never starts, days after the operator stopped suspecting TLS.
CERT_DIR="/etc/letsencrypt/live/${HOPEFX_DOMAIN}"
if [ ! -f "${CERT_DIR}/fullchain.pem" ] || [ ! -f "${CERT_DIR}/privkey.pem" ]; then
    echo "" >&2
    echo "[entrypoint] No TLS certificate for ${HOPEFX_DOMAIN}." >&2
    echo "" >&2
    echo "  Expected both of:" >&2
    echo "      ${CERT_DIR}/fullchain.pem" >&2
    echo "      ${CERT_DIR}/privkey.pem" >&2
    echo "" >&2
    echo "  nginx treats a missing ssl_certificate as a fatal config error, so it" >&2
    echo "  would exit here with a message about a file rather than about TLS." >&2
    echo "" >&2
    echo "  Issue one (DNS for ${HOPEFX_DOMAIN} must already point at this host):" >&2
    echo "      docker run --rm -p 80:80 \\" >&2
    echo "        -v /etc/letsencrypt:/etc/letsencrypt \\" >&2
    echo "        -v /var/www/certbot:/var/www/certbot \\" >&2
    echo "        certbot/certbot certonly --standalone -d ${HOPEFX_DOMAIN} -d www.${HOPEFX_DOMAIN}" >&2
    echo "" >&2
    echo "  Or do not run this container at all. It binds :80 and :443, so it" >&2
    echo "  collides with any proxy already holding them — a Hostinger VPS runs" >&2
    echo "  traefik by default. When something in front already terminates TLS," >&2
    echo "  point it at the app service on port 8000 and drop nginx:" >&2
    echo "      docker compose stop nginx && docker compose rm -f nginx" >&2
    echo "" >&2
    echo "  There is deliberately no HTTP-only mode here: every location block" >&2
    echo "  lives inside the TLS server, so stripping TLS removes the proxy with" >&2
    echo "  it and leaves a config that does not parse." >&2
    echo "" >&2
    exit 1
fi

# Fail on a bad config here, where the message is visible, rather than leaving
# nginx to exit during startup.
nginx -t

exec nginx -g "daemon off;"
