#!/bin/bash
set -e

# Environment validation
: "${APP_ENV:?APP_ENV must be set}"
: "${DATABASE_URL:?DATABASE_URL must be set}"

# Wait for dependencies
wait_for_service() {
    local host=$1
    local port=$2
    local service=$3
    
    echo "Waiting for $service at $host:$port..."
    while ! nc -z $host $port; do
        sleep 1
    done
    echo "$service is ready"
}

# Extract host/port from URLs
if [[ $DATABASE_URL == *"localhost"* ]] || [[ $DATABASE_URL == *"postgres"* ]]; then
    wait_for_service postgres 5432 "PostgreSQL"
fi

if [[ $REDIS_URL == *"localhost"* ]] || [[ $REDIS_URL == *"redis"* ]]; then
    wait_for_service redis 6379 "Redis"
fi

# Run database migrations if API server
if [ "$1" = "api" ] || [ "$1" = "server" ]; then
    echo "Running database migrations..."
    cd /app && alembic upgrade head || echo "Migration warning (continuing)"
fi

# Execute command
case "$1" in
    api|server)
        echo "Starting API server..."
        exec python -m hopefx server
        ;;
    worker)
        echo "Starting background worker..."
        exec python -m hopefx worker
        ;;
    bot)
        echo "Starting XAUUSD bot..."
        exec python scripts/xauusd_bot.py "${@:2}"
        ;;
    migrate)
        echo "Running migrations..."
        exec alembic upgrade head
        ;;
    shell)
        exec /bin/bash
        ;;
    *)
        exec "$@"
        ;;
esac
