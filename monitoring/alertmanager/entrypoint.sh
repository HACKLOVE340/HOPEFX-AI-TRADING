#!/bin/sh
# monitoring/alertmanager/entrypoint.sh
# Expands ${VAR:-default} placeholders in alertmanager.yml.tmpl using shell
# evaluation (not envsubst, which does not support :- defaults), then execs
# the real alertmanager binary.
set -eu

TMPL=/etc/alertmanager/alertmanager.yml.tmpl
OUT=/tmp/alertmanager.yml

while IFS= read -r line || [ -n "$line" ]; do
    eval "printf '%s\n' \"$line\""
done < "$TMPL" > "$OUT"

exec /bin/alertmanager \
    --config.file="$OUT" \
    --storage.path=/alertmanager \
    --web.listen-address=:9093 \
    --cluster.listen-address= \
    "$@"
