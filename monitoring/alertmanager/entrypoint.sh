#!/bin/sh
# monitoring/alertmanager/entrypoint.sh
# Expands ${VAR:-default} placeholders in alertmanager.yml.tmpl using the
# container's environment variables, then execs the real alertmanager binary.
set -eu

TMPL=/etc/alertmanager/alertmanager.yml.tmpl
OUT=/tmp/alertmanager.yml

envsubst < "$TMPL" > "$OUT"

exec /bin/alertmanager \
    --config.file="$OUT" \
    --storage.path=/alertmanager \
    --web.listen-address=:9093 \
    --cluster.listen-address= \
    "$@"
