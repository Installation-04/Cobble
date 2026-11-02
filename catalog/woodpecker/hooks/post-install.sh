#!/usr/bin/env bash
# Once Woodpecker runs: mints the API token the core uses, by signing in as the Git server's
# service account (headless OAuth, see wp_login.py). Idempotent: a stored token that still works
# is kept. The hook runs in the module-manager's container, which is on the platform network.
set -euo pipefail

: "${COBBLE_PEER_GIT_HOST:?}" "${COBBLE_PEER_GIT_PORT:?}" "${COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD:?}"
: "${COBBLE_PUBLIC_URL:?}" "${COBBLE_MODULE_ID:?}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CI="http://cobble-${COBBLE_MODULE_ID}-server:8000"
GIT="http://${COBBLE_PEER_GIT_HOST}:${COBBLE_PEER_GIT_PORT}"

log() { printf '[woodpecker] %s\n' "$*" >&2; }

token_ok() { # token_ok TOKEN: does the CI API accept it?
  [ -n "$1" ] && python3 -I - "$CI" "$1" <<'PY'
import sys, urllib.request
request = urllib.request.Request(sys.argv[1] + "/ci/api/user", headers={"Authorization": "Bearer " + sys.argv[2]})
try:
    sys.exit(0 if urllib.request.urlopen(request, timeout=10).status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

existing="${COBBLE_SECRET_API_TOKEN:-}"
if token_ok "$existing"; then
  log "the API token still works"
  printf '::secret::api_token=%s\n' "$existing"
  exit 0
fi

log "minting the API token (headless OAuth sign-in of the service account)"
export COBBLE_SERVICE_USER=cobble-bot COBBLE_SERVICE_PASSWORD="$COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD"
token="$(python3 -I "$HERE/wp_login.py" "$COBBLE_PUBLIC_URL" "$GIT" "$CI")" \
  || { log "cannot obtain the CI token"; exit 1; }
[ -n "$token" ] || { log "the CI returned no token"; exit 1; }
printf '::secret::api_token=%s\n' "$token"
