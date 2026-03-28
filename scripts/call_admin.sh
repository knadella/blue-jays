#!/usr/bin/env bash
# Call production (or local) admin endpoints from cron, GitHub Actions, or systemd.
#
# Usage:
#   API_BASE_URL=https://api.example.com ADMIN_API_KEY=secret ./scripts/call_admin.sh refresh
#   API_BASE_URL=https://api.example.com ADMIN_API_KEY=secret ./scripts/call_admin.sh refit
#
# Optional: MLB_SEASON=2026 (defaults to server env / config)
#
set -euo pipefail

JOB="${1:-refresh}"
BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
SEASON_QS=""
if [[ -n "${MLB_SEASON:-}" ]]; then
  SEASON_QS="?season=${MLB_SEASON}"
fi

HDR=()
if [[ -n "${ADMIN_API_KEY:-}" ]]; then
  HDR=(-H "X-Admin-Key: ${ADMIN_API_KEY}")
fi

case "$JOB" in
  refresh)
    curl -fsS --max-time "${CURL_MAX_TIME:-180}" -X POST \
      "${BASE_URL}/api/admin/refresh-actuals${SEASON_QS}" "${HDR[@]}"
    ;;
  refit)
    curl -fsS --max-time "${CURL_MAX_TIME:-900}" -X POST \
      "${BASE_URL}/api/admin/refit-model${SEASON_QS}" "${HDR[@]}"
    ;;
  *)
    echo "Usage: $0 refresh|refit" >&2
    exit 1
    ;;
esac

echo
