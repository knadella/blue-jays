#!/usr/bin/env bash
# Set Actions secrets for scheduled refresh/refit workflows.
#
# Usage:
#   export GITHUB_REPO=owner/repo   # default: knadella/blue-jays
#   ./scripts/set_github_actions_secrets.sh https://your-api.example.com
#
# Optional second arg reuses an existing admin key; otherwise a new one is
# generated and printed once (use the same value as ADMIN_API_KEY on your host).
#
set -euo pipefail

REPO="${GITHUB_REPO:-knadella/blue-jays}"
BASE_URL="${1:?Usage: $0 https://your-api-host (no trailing slash) [optional_admin_key]}"
BASE_URL="${BASE_URL%/}"
ADMIN_KEY="${2:-$(openssl rand -hex 32)}"

command -v gh >/dev/null || { echo "Install GitHub CLI: https://cli.github.com" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Run: gh auth login" >&2; exit 1; }

printf '%s' "$ADMIN_KEY" | gh secret set ADMIN_API_KEY -R "$REPO"
printf '%s' "$BASE_URL" | gh secret set API_BASE_URL -R "$REPO"

echo "Repository secrets set for $REPO"
echo "  API_BASE_URL=$BASE_URL"
echo "  ADMIN_API_KEY=(stored; use the same value below on your server)"
echo ""
echo "Set on your API host (Fly/Railway/etc.):"
echo "  ADMIN_API_KEY=$ADMIN_KEY"
