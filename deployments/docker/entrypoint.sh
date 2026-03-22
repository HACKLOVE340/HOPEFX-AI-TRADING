#!/bin/bash
set -e

# Wait for dependencies
echo "Waiting for database..."
until pg_isready -h "${DB_HOST:-db}" -p "${DB_PORT:-5432}" -U "${DB_USER:-postgres}"; do
  sleep 1
done

echo "Waiting for Redis..."
until redis-cli -h "${REDIS_HOST:-redis}" -p "${REDIS_PORT:-6379}" ping; do
  sleep 1
done

echo "Dependencies ready. Starting application..."

# Run database migrations
alembic upgrade head

# Start application
exec "$@"
