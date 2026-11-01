#!/usr/bin/env bash
# Creates Forgejo's service account and its API token. Idempotent: an existing account is kept,
# and a stored token that still works is left alone. The token is handed back to the platform
# as `::secret::api_token=...` (the only line of output that is read).
set -euo pipefail

CONTAINER="cobble-${COBBLE_MODULE_ID}-forgejo"
USER_NAME="cobble-bot"
: "${COBBLE_SECRET_ADMIN_PASSWORD:?}"
export USER_NAME COBBLE_SECRET_ADMIN_PASSWORD COBBLE_SECRET_API_TOKEN="${COBBLE_SECRET_API_TOKEN:-}"

log() { printf '[forgejo] %s\n' "$*" >&2; }

# Runs a command in the container; credentials travel by variable name, not on the command line.
in_forgejo() {
  docker exec -i -e USER_NAME -e COBBLE_SECRET_ADMIN_PASSWORD -e COBBLE_SECRET_API_TOKEN "$CONTAINER" "$@"
}

# api basic|token METHOD PATH [json body on stdin] -> body, then a last line with the HTTP code
api() {
  in_forgejo sh -c '
    kind="$1"; method="$2"; url="http://localhost:3000/api/v1$3"; body="$(cat)"
    if [ "$kind" = token ]; then set -- -H "Authorization: token $COBBLE_SECRET_API_TOKEN"
    else set -- -u "$USER_NAME:$COBBLE_SECRET_ADMIN_PASSWORD"; fi
    if [ -n "$body" ]; then
      curl -sS -w "\n%{http_code}" "$@" -H "Content-Type: application/json" -X "$method" -d "$body" "$url"
    else
      curl -sS -w "\n%{http_code}" "$@" -X "$method" "$url"
    fi' _ "$1" "$2" "$3"
}
code() { tail -n 1; }
body() { sed '$d'; }

if ! in_forgejo forgejo admin user list </dev/null | awk 'NR>1 {print $2}' | grep -qx "$USER_NAME"; then
  log "creating the service account"
  in_forgejo sh -c 'forgejo admin user create --admin --username "$USER_NAME" \
      --password "$COBBLE_SECRET_ADMIN_PASSWORD" --email "$USER_NAME@cobble.invalid" \
      --must-change-password=false' </dev/null >/dev/null
fi

if [ -n "$COBBLE_SECRET_API_TOKEN" ] && [ "$(api token GET /user </dev/null | code)" = 200 ]; then
  log "the API token still works"
  printf '::secret::api_token=%s\n' "$COBBLE_SECRET_API_TOKEN"
  exit 0
fi

log "creating the API token"
api basic DELETE "/users/$USER_NAME/tokens/cobble-core" </dev/null >/dev/null || true
out="$(api basic POST "/users/$USER_NAME/tokens" <<<'{"name":"cobble-core","scopes":["write:repository","write:user","write:organization","read:misc"]}')"
[ "$(printf '%s\n' "$out" | code)" = 201 ] || { log "cannot create the API token"; exit 1; }
token="$(printf '%s\n' "$out" | body | python3 -c 'import json,sys; print(json.load(sys.stdin).get("sha1", ""))')"
[ -n "$token" ] || { log "the server returned no token"; exit 1; }
printf '::secret::api_token=%s\n' "$token"
