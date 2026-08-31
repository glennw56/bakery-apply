#!/bin/sh
# One-time (or anytime) local install. Run from repo root, or via this script's path.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

mkdir -p data

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Wrote .env from .env.example — change SESSION_SECRET / ADMIN_PASSWORD before anything public."
fi

echo "Setup done. Start with: ./scripts/run.sh"
