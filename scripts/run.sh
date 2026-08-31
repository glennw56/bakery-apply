#!/bin/sh
# Start uvicorn. HOST=127.0.0.1 PORT=8000 RELOAD=1 by default.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "No .venv (or uvicorn missing). Run ./scripts/setup.sh first." >&2
  exit 1
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-1}"

set -- .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT"
case "$RELOAD" in
  1|true|TRUE|yes|YES) set -- "$@" --reload ;;
esac

echo "Listening on http://${HOST}:${PORT}  (RELOAD=${RELOAD})"
echo "Apply       http://${HOST}:${PORT}/"
echo "Admin       http://${HOST}:${PORT}/admin"
PYTHONPATH=. exec "$@"
