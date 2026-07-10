#!/usr/bin/env bash
# One command: generate the static site data, then serve the frontend on :5173.
# (There is no backend server anymore — the frontend reads /data/*.json.)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY=".venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

echo "Building site data → frontend/public/data …"
"$PY" scripts/build_site_data.py

echo "Starting Vite on http://127.0.0.1:5173/"
cd frontend
exec npm run dev -- --host 127.0.0.1
