#!/usr/bin/env bash
# Before Woodpecker starts: registers it as an OAuth application of the Git server (which is
# already running: Woodpecker requires `git`), and hands the client id and secret back to the
# platform, which gives them to Woodpecker's compose file. Idempotent: an application of the same
# name is replaced.
set -euo pipefail

: "${COBBLE_PEER_GIT_HOST:?}" "${COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD:?}" "${COBBLE_PUBLIC_URL:?}"
export COBBLE_SERVICE_USER=cobble-bot COBBLE_SERVICE_PASSWORD="$COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD"
APP_NAME=woodpecker

log() { printf '[woodpecker] %s\n' "$*" >&2; }

# api METHOD PATH [json body on stdin] -> body, then a last line with the HTTP code. The call is
# made from inside the Git server's container; the password travels by variable name.
api() {
  docker exec -i -e COBBLE_SERVICE_USER -e COBBLE_SERVICE_PASSWORD "$COBBLE_PEER_GIT_HOST" sh -c '
    method="$1"; url="http://localhost:3000/api/v1$2"; body="$(cat)"
    if [ -n "$body" ]; then
      curl -sS -w "\n%{http_code}" -u "$COBBLE_SERVICE_USER:$COBBLE_SERVICE_PASSWORD" \
        -H "Content-Type: application/json" -X "$method" -d "$body" "$url"
    else
      curl -sS -w "\n%{http_code}" -u "$COBBLE_SERVICE_USER:$COBBLE_SERVICE_PASSWORD" -X "$method" "$url"
    fi' _ "$1" "$2"
}
code() { tail -n 1; }
body() { sed '$d'; }
json() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get(sys.argv[1], ""))' "$1"; }

# Remove an application of the same name left by an earlier attempt.
listing="$(api GET /user/applications/oauth2 </dev/null)"
if [ "$(printf '%s\n' "$listing" | code)" = 200 ]; then
  old_ids="$(printf '%s\n' "$listing" | body | python3 -c '
import json, sys
for app in json.load(sys.stdin):
    if app.get("name") == "'"$APP_NAME"'":
        print(app["id"])')"
  for id in $old_ids; do api DELETE "/user/applications/oauth2/$id" </dev/null >/dev/null || true; done
fi

log "registering the OAuth application"
payload="{\"name\":\"$APP_NAME\",\"redirect_uris\":[\"$COBBLE_PUBLIC_URL/ci/authorize\"],\"confidential_client\":true}"
out="$(api POST /user/applications/oauth2 <<<"$payload")"
[ "$(printf '%s\n' "$out" | code)" = 201 ] || { log "the Git server refused the application"; exit 1; }
app="$(printf '%s\n' "$out" | body)"
printf '::secret::oauth_app_id=%s\n' "$(printf '%s' "$app" | json id)"
printf '::secret::forgejo_client=%s\n' "$(printf '%s' "$app" | json client_id)"
printf '::secret::forgejo_secret=%s\n' "$(printf '%s' "$app" | json client_secret)"
