#!/usr/bin/env bash
# Before Woodpecker is removed: deletes its OAuth application from the Git server. Best effort
# (the platform removes the module whatever happens here).
set -euo pipefail

: "${COBBLE_PEER_GIT_HOST:=}" "${COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD:=}"
app_id="${COBBLE_SECRET_OAUTH_APP_ID:-}"
[ -n "$COBBLE_PEER_GIT_HOST" ] && [ -n "$COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD" ] && [ -n "$app_id" ] || exit 0
export COBBLE_SERVICE_USER=cobble-bot COBBLE_SERVICE_PASSWORD="$COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD" APP_ID="$app_id"
docker exec -e COBBLE_SERVICE_USER -e COBBLE_SERVICE_PASSWORD -e APP_ID "$COBBLE_PEER_GIT_HOST" sh -c \
  'curl -sS -o /dev/null -u "$COBBLE_SERVICE_USER:$COBBLE_SERVICE_PASSWORD" -X DELETE "http://localhost:3000/api/v1/user/applications/oauth2/$APP_ID"' \
  </dev/null || true
echo "[woodpecker] OAuth application removed" >&2
