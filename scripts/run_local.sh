#!/usr/bin/env bash
# Start the Vite UI after verifying the FastAPI process answers on 127.0.0.1:8000.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! curl -4 -sf --max-time 3 "http://127.0.0.1:8000/api/health" >/dev/null; then
  echo "Nothing is responding at http://127.0.0.1:8000/api/health (used curl -4 for IPv4)"
  echo "In a separate terminal, from the repo root, run:"
  echo "  .venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000"
  echo "Then run this script again."
  exit 1
fi

echo "API OK. Starting Vite on http://127.0.0.1:5173/ (unset VITE_API_URL in .env so /api proxies to 8000)."
cd frontend
exec npm run dev -- --host 127.0.0.1
