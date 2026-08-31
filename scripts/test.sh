#!/bin/sh
# pytest -q from repo root.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -x .venv/bin/pytest ]; then
  echo "No .venv (or pytest missing). Run ./scripts/setup.sh first." >&2
  exit 1
fi

PYTHONPATH=. .venv/bin/pytest -q
