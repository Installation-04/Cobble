#!/usr/bin/env bash
# Before Woodpecker is removed: stops its agent, removes the pipeline resources the agent created
# on the host (they live outside the module's compose project, so removing the project would leave
# them behind), and deletes the OAuth application from the Git server. Best effort throughout
# (the platform removes the module whatever happens here).
set -euo pipefail

log() { printf '[woodpecker] %s\n' "$*" >&2; }

# 1. no new pipeline may start while we clean up
docker stop "cobble-${COBBLE_MODULE_ID:-woodpecker}-agent" >/dev/null 2>&1 || true

# 2. what the agent created: step containers (label wp_uuid), their volumes and networks
# (named wp_<id>_<n>_default). Only Woodpecker creates resources with these names.
containers="$(docker ps -aq --filter label=wp_uuid 2>/dev/null || true)"
# shellcheck disable=SC2086  # the ids are space separated on purpose
[ -z "$containers" ] || docker rm -f $containers >/dev/null 2>&1 || true
for volume in $(docker volume ls -q 2>/dev/null | grep -E '^wp_[0-9a-z]+_[0-9]+_default$' || true); do
  docker volume rm -f "$volume" >/dev/null 2>&1 || true
done
for network in $(docker network ls --format '{{.Name}}' 2>/dev/null | grep -E '^wp_[0-9a-z]+_[0-9]+_default$' || true); do
  docker network rm "$network" >/dev/null 2>&1 || true
done
log "pipeline leftovers removed"

# 3. the OAuth application
: "${COBBLE_PEER_GIT_HOST:=}" "${COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD:=}"
app_id="${COBBLE_SECRET_OAUTH_APP_ID:-}"
[ -n "$COBBLE_PEER_GIT_HOST" ] && [ -n "$COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD" ] && [ -n "$app_id" ] || exit 0
export COBBLE_SERVICE_USER=cobble-bot COBBLE_SERVICE_PASSWORD="$COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD" APP_ID="$app_id"
docker exec -e COBBLE_SERVICE_USER -e COBBLE_SERVICE_PASSWORD -e APP_ID "$COBBLE_PEER_GIT_HOST" sh -c \
  'curl -sS -o /dev/null -u "$COBBLE_SERVICE_USER:$COBBLE_SERVICE_PASSWORD" -X DELETE "http://localhost:3000/api/v1/user/applications/oauth2/$APP_ID"' \
  </dev/null || true
log "OAuth application removed"
