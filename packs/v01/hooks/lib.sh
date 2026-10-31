# shellcheck shell=bash
# Shared helpers of the pack hooks. Developer-facing scripts: messages are in English.
# Secrets are read from / written to files with mode 600 and never echoed.

PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${COBBLE_PACK_ENV:-$PACK_DIR/.env}"          # compose variables + wiring state (secret)
CORE_ENV_FILE="${COBBLE_PACK_CORE_ENV:-$PACK_DIR/.env.pack}"  # what the core reads (secret)
# Pinned by digest, like every image (CLAUDE.md rule 9). Runs the headless login helper.
PYTHON_IMAGE="python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159"
PACK_NETWORK="cobble-pack-internal"

log() { printf '[pack] %s\n' "$*" >&2; }
die() { printf '[pack] error: %s\n' "$*" >&2; exit 1; }

# docker compose for this pack. COBBLE_PACK_PROJECT renames the compose project (tests),
# COBBLE_PACK_COMPOSE_EXTRA is a list of extra "-f file" overrides.
compose() {
  local extra=()
  # shellcheck disable=SC2206  # word splitting of the override list is intended
  [ -n "${COBBLE_PACK_COMPOSE_EXTRA:-}" ] && extra=(${COBBLE_PACK_COMPOSE_EXTRA})
  docker compose --project-directory "$PACK_DIR" ${COBBLE_PACK_PROJECT:+-p "$COBBLE_PACK_PROJECT"} \
    -f "$PACK_DIR/compose.yml" "${extra[@]}" "$@"
}

env_get() { # env_get FILE KEY
  [ -f "$1" ] || return 0
  sed -n "s/^$2=//p" "$1" | tail -n 1
}

env_set() { # env_set FILE KEY VALUE  (replace or append, mode 600, value never printed)
  local file="$1" key="$2" value="$3" tmp
  ( umask 077
    tmp="$(mktemp "$file.XXXXXX")"
    if [ -f "$file" ]; then grep -v "^$key=" "$file" >"$tmp" || true; fi
    printf '%s=%s\n' "$key" "$value" >>"$tmp"
    mv "$tmp" "$file" )
  chmod 600 "$file"
}

gen_secret() { # 64 hex characters
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 32
  else head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; echo; fi
}

wait_healthy() { # wait_healthy SERVICE [SECONDS]
  local service="$1" limit="${2:-180}" cid status i=0
  while [ "$i" -lt "$limit" ]; do
    cid="$(compose ps -q "$service" 2>/dev/null || true)"
    if [ -n "$cid" ]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      [ "$status" = "healthy" ] && return 0
    fi
    sleep 2; i=$((i + 2))
  done
  die "$service is not healthy after ${limit}s (docker compose logs $service)"
}

# Call the Forgejo API from inside its container (no host port needed). Credentials are passed
# by variable NAME (exported in this shell), so they never show up in a process list.
#   fapi basic|token METHOD PATH   (optional JSON body on stdin)
# prints the response body, then a last line holding the HTTP status code.
fapi() {
  compose exec -T -e PACK_SERVICE_USER -e PACK_SERVICE_PASSWORD -e PACK_FORGEJO_TOKEN forgejo sh -c '
    kind="$1"; method="$2"; url="http://localhost:3000/api/v1$3"; body="$(cat)"
    if [ "$kind" = token ]; then set -- -H "Authorization: token $PACK_FORGEJO_TOKEN"
    else set -- -u "$PACK_SERVICE_USER:$PACK_SERVICE_PASSWORD"; fi
    if [ -n "$body" ]; then
      curl -sS -w "\n%{http_code}" "$@" -H "Content-Type: application/json" -X "$method" -d "$body" "$url"
    else
      curl -sS -w "\n%{http_code}" "$@" -X "$method" "$url"
    fi' _ "$1" "$2" "$3"
}
fapi0() { fapi "$@" </dev/null; } # no request body
http_code() { tail -n 1; }
http_body() { sed '$d'; }

json_get() { # json_get KEY  (reads JSON on stdin; prints the top-level string value)
  python3 -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1], ""))' "$1"
}
