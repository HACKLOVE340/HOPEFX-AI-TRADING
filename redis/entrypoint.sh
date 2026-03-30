#!/bin/sh
# redis/entrypoint.sh
# Replaces password placeholders in Redis/Sentinel config at container start,
# then exec's the real Redis/Sentinel process.
#
# Required env vars:
#   REDIS_PASSWORD          — Redis auth password
#   REDIS_CONFIG_FILE       — path to the config file to patch
#   REDIS_PROCESS           — "redis-server" or "redis-sentinel"

set -e

CONFIG="${REDIS_CONFIG_FILE:-/etc/redis/redis.conf}"
PROCESS="${REDIS_PROCESS:-redis-server}"
PASSWORD="${REDIS_PASSWORD:?REDIS_PASSWORD must be set}"

# Replace placeholder with real password in-place
sed -i "s/REDIS_PASSWORD_PLACEHOLDER/${PASSWORD}/g" "${CONFIG}"
sed -i "s/REDIS_SENTINEL_PASSWORD_PLACEHOLDER/${PASSWORD}/g" "${CONFIG}"

exec "${PROCESS}" "${CONFIG}"
