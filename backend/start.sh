#!/usr/bin/env sh
# ---------------------------------------------------------------------------
# start.sh — Backend entrypoint for Render deployments.
#
# Render's managed PostgreSQL provides a DATABASE_URL in the form:
#   postgresql://user:pass@host:5432/db
#
# SQLAlchemy async engine (asyncpg) requires:
#   postgresql+asyncpg://user:pass@host:5432/db
#
# This script patches the URL, runs Alembic migrations, then starts uvicorn.
# ---------------------------------------------------------------------------
set -e

# ---------- 1. Fix DATABASE_URL scheme for asyncpg -------------------------
if [ -n "$DATABASE_URL" ]; then
    # Replace leading "postgresql://" (or "postgres://") with asyncpg variant
    export DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|^postgres://|postgresql+asyncpg://|;s|^postgresql://|postgresql+asyncpg://|')
    echo "[start.sh] DATABASE_URL scheme fixed → ${DATABASE_URL%%@*}@..."
fi

# ---------- 2. Run database migrations -------------------------------------
echo "[start.sh] Running Alembic migrations..."
alembic upgrade head

# ---------- 3. Start the application ---------------------------------------
echo "[start.sh] Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
