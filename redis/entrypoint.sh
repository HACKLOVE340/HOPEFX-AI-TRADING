#!/bin/sh
# redis/entrypoint.sh
# Replaces placeholders in Redis/Sentinel config at container start,
# then exec's the real Redis/Sentinel process.
#
# Required env vars:
#   REDIS_PASSWORD          — Redis auth password
#   REDIS_CONFIG_FILE       — path to the config file to patch (default: /etc/redis/redis.conf)
#   REDIS_PROCESS           — "redis-server" or "redis-sentinel" (default: redis-server)
#
# Optional env vars:
#   REDIS_MAXMEMORY         — Redis maxmemory value (default: 512mb)
#                             Examples: 512mb, 1gb, 2gb
#                             Set higher on VPS instances with more RAM.

set -e

CONFIG="${REDIS_CONFIG_FILE:-/etc/redis/redis.conf}"
PROCESS="${REDIS_PROCESS:-redis-server}"
PASSWORD="${REDIS_PASSWORD:?REDIS_PASSWORD must be set}"
MAXMEMORY="${REDIS_MAXMEMORY:-512mb}"

# Replace password placeholders
sed -i "s/REDIS_PASSWORD_PLACEHOLDER/${PASSWORD}/g" "${CONFIG}"
sed -i "s/REDIS_SENTINEL_PASSWORD_PLACEHOLDER/${PASSWORD}/g" "${CONFIG}"

# Replace maxmemory placeholder — Redis does not expand shell variables,
# so we substitute at container start time instead.
sed -i "s|\${REDIS_MAXMEMORY:-512mb}|${MAXMEMORY}|g" "${CONFIG}"

exec "${PROCESS}" "${CONFIG}"
