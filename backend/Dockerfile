FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

# Make startup script executable
RUN chmod +x /app/start.sh

EXPOSE 8000

# Use start.sh which handles:
#   1. DATABASE_URL scheme conversion (postgres:// → postgresql+asyncpg://)
#   2. Alembic migrations
#   3. uvicorn startup (respects $PORT set by Render)
CMD ["/app/start.sh"]
