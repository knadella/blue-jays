#!/usr/bin/env bash
# One command: FastAPI on :8000 then Vite on :5173 (Vite proxies /api → 8000).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -4 -sf --max-time 2 "http://127.0.0.1:8000/api/health" >/dev/null; then
    echo "Port 8000 already in use — API looks healthy. Starting Vite only."
    cd frontend && exec npm run dev -- --host 127.0.0.1
  fi
  echo "Port 8000 is in use but http://127.0.0.1:8000/api/health did not respond in time."
  echo "Something else (often a stuck uvicorn) is bound there. Free the port, then retry:"
  echo "  lsof -nP -iTCP:8000 -sTCP:LISTEN"
  echo "  kill <PID>    # use kill -9 <PID> only if the process ignores SIGTERM"
  exit 1
fi

cleanup() {
  if [[ -n "${UV_PID:-}" ]] && kill -0 "$UV_PID" 2>/dev/null; then
    kill "$UV_PID" 2>/dev/null || true
    wait "$UV_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Starting API on http://127.0.0.1:8000 …"
echo "(If curl to http://localhost:8000 hangs, use 127.0.0.1 or curl -4 — macOS often tries IPv6 first.)"
.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000 &
UV_PID=$!

api_ok=0
for _ in $(seq 1 80); do
  if curl -4 -sf --max-time 1 "http://127.0.0.1:8000/api/health" >/dev/null; then
    api_ok=1
    break
  fi
  if ! kill -0 "$UV_PID" 2>/dev/null; then
    echo "uvicorn exited before becoming healthy; check errors above."
    exit 1
  fi
  sleep 0.15
done
if [[ "$api_ok" -ne 1 ]]; then
  echo "Timed out waiting for http://127.0.0.1:8000/api/health (uvicorn still running?)."
  exit 1
fi

echo "API OK. Starting Vite on http://127.0.0.1:5173/"
cd frontend
npm run dev -- --host 127.0.0.1
