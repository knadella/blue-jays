#!/usr/bin/env bash
# Start the Vite UI, assuming site data has already been generated.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! ls frontend/public/data/players_*.json >/dev/null 2>&1; then
  echo "No site data in frontend/public/data/. Generate it first:"
  echo "  .venv/bin/python scripts/build_site_data.py"
  exit 1
fi

echo "Site data found. Starting Vite on http://127.0.0.1:5173/"
cd frontend
exec npm run dev -- --host 127.0.0.1
