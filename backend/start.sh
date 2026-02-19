#!/usr/bin/env sh
# ---------------------------------------------------------------------------
# start.sh — Backend entrypoint for Render deployments (free tier).
#
# Render's free plan does not support background worker services, so we
# run both the FastAPI server and the Celery worker in the same container.
#
# Boot sequence:
#   1. Patch DATABASE_URL scheme: postgres:// → postgresql+asyncpg://
#   2. Run Alembic migrations
#   3. Start Celery worker in the background
#   4. Start uvicorn in the foreground (keeps the container alive)
# ---------------------------------------------------------------------------
set -e

# ---------- 1. Fix DATABASE_URL scheme for asyncpg -------------------------
if [ -n "$DATABASE_URL" ]; then
    export DATABASE_URL=$(echo "$DATABASE_URL" | sed \
        's|^postgres://|postgresql+asyncpg://|;s|^postgresql://|postgresql+asyncpg://|')
    echo "[start.sh] DATABASE_URL scheme → ${DATABASE_URL%%@*}@..."
fi

# ---------- 2. Run database migrations -------------------------------------
echo "[start.sh] Running Alembic migrations..."
alembic upgrade head

# ---------- 3. Start Celery worker in background ---------------------------
echo "[start.sh] Starting Celery worker (background)..."
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2 &
CELERY_PID=$!
echo "[start.sh] Celery PID: $CELERY_PID"

# ---------- 4. Start uvicorn (foreground — keeps the dyno alive) -----------
echo "[start.sh] Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
