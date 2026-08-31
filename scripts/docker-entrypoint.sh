#!/bin/sh
# Cloud Run / Docker: listen on 0.0.0.0 and $PORT. Admin is seeded on app startup.
set -eu
cd /app
mkdir -p /app/data
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
