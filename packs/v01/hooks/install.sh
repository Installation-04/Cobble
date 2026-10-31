#!/usr/bin/env bash
# Install / repair the v0.1 pack and wire its parts together, headlessly. Idempotent:
# existing secrets are kept unless --rotate is given.
#
#   COBBLE_PACK_PUBLIC_URL   URL users reach the core at, e.g. http://192.168.1.20 (default
#                            http://localhost). Forgejo is served under <url>/git/, the CI
#                            under <url>/ci/ (core Caddy: see caddy/pack.caddy).
#   COBBLE_PACK_PROJECT      compose project name override (tests only)
#   COBBLE_PACK_COMPOSE_EXTRA  extra "-f override.yml" arguments (tests only)
#
# Usage: hooks/install.sh [--rotate]
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ROTATE=0
case "${1:-}" in
  --rotate) ROTATE=1 ;;
  "") ;;
  *) die "usage: install.sh [--rotate]" ;;
esac

command -v docker >/dev/null || die "docker is required"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is required"
docker network inspect cobble_core >/dev/null 2>&1 \
  || die "network cobble_core not found: start the Cobble core first (make dev)"
docker info >/dev/null 2>&1 || die "cannot talk to the docker daemon"

# --- 1. secrets and settings (.env, mode 600) --------------------------------------------
touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
ensure() { # ensure KEY VALUE: set only when missing (or when rotating)
  if [ -z "$(env_get "$ENV_FILE" "$1")" ] || [ "$ROTATE" = 1 ]; then env_set "$ENV_FILE" "$1" "$2"; fi
}
public_url="${COBBLE_PACK_PUBLIC_URL:-$(env_get "$ENV_FILE" PACK_PUBLIC_URL)}"
public_url="${public_url:-http://localhost}"
public_url="${public_url%/}"
case "$public_url" in http://*|https://*) ;; *) die "COBBLE_PACK_PUBLIC_URL must start with http:// or https://" ;; esac
hostport="${public_url#*://}"; hostport="${hostport%%/*}"
host="${hostport%%:*}"; port="${hostport#"$host"}"; port="${port#:}"
if [ -z "$port" ]; then case "$public_url" in https://*) port=443 ;; *) port=80 ;; esac; fi
alias_host=pack-gateway
case "$host" in *[!0-9.]*) alias_host="$host" ;; esac  # a name (not an IPv4): pipelines resolve it

env_set "$ENV_FILE" PACK_PUBLIC_URL "$public_url"
env_set "$ENV_FILE" PACK_PUBLIC_HOST "$host"
env_set "$ENV_FILE" PACK_PUBLIC_PORT "$port"
env_set "$ENV_FILE" PACK_GATEWAY_ALIAS "$alias_host"
env_set "$ENV_FILE" DOCKER_GID "$(stat -c %g /var/run/docker.sock)"
ensure PACK_SERVICE_USER cobble-bot
ensure PACK_SERVICE_PASSWORD "$(gen_secret)"
ensure FORGEJO_SECRET_KEY "$(gen_secret)"
ensure WOODPECKER_AGENT_SECRET "$(gen_secret)"
ensure WOODPECKER_GRPC_SECRET "$(gen_secret)"

# Exported by NAME for the docker exec calls (see lib.sh).
PACK_SERVICE_USER="$(env_get "$ENV_FILE" PACK_SERVICE_USER)"
PACK_SERVICE_PASSWORD="$(env_get "$ENV_FILE" PACK_SERVICE_PASSWORD)"
PACK_FORGEJO_TOKEN="$(env_get "$ENV_FILE" PACK_FORGEJO_TOKEN)"
export PACK_SERVICE_USER PACK_SERVICE_PASSWORD PACK_FORGEJO_TOKEN

# --- 2. git server -----------------------------------------------------------------------
log "starting the git server"
compose up -d forgejo pack-gateway >&2
wait_healthy forgejo

if ! compose exec -T forgejo forgejo admin user list 2>/dev/null | awk 'NR>1 {print $2}' | grep -qx "$PACK_SERVICE_USER"; then
  log "creating the service account $PACK_SERVICE_USER"
  compose exec -T -e PACK_SERVICE_USER -e PACK_SERVICE_PASSWORD forgejo sh -c \
    'forgejo admin user create --admin --username "$PACK_SERVICE_USER" --password "$PACK_SERVICE_PASSWORD" \
       --email "$PACK_SERVICE_USER@cobble.invalid" --must-change-password=false' >/dev/null
fi

token_ok() { [ -n "$PACK_FORGEJO_TOKEN" ] && [ "$(fapi0 token GET /user | http_code)" = 200 ]; }
if [ "$ROTATE" = 1 ] || ! token_ok; then
  log "creating the git API token"
  fapi0 basic DELETE "/users/$PACK_SERVICE_USER/tokens/cobble-core" >/dev/null || true
  out="$(fapi basic POST "/users/$PACK_SERVICE_USER/tokens" <<<'{"name":"cobble-core","scopes":["write:repository","write:user","write:organization","read:misc"]}')"
  [ "$(printf '%s\n' "$out" | http_code)" = 201 ] || die "cannot create the git API token"
  PACK_FORGEJO_TOKEN="$(printf '%s\n' "$out" | http_body | json_get sha1)"
  [ -n "$PACK_FORGEJO_TOKEN" ] || die "the git server returned no token"
  export PACK_FORGEJO_TOKEN
  env_set "$ENV_FILE" PACK_FORGEJO_TOKEN "$PACK_FORGEJO_TOKEN"
fi

# --- 3. OAuth application of the CI in the git server -------------------------------------
redirect="[\"$public_url/ci/authorize\"]"
app_id="$(env_get "$ENV_FILE" PACK_OAUTH_APP_ID)"
if [ -z "$app_id" ] || [ -z "$(env_get "$ENV_FILE" WOODPECKER_FORGEJO_CLIENT)" ] || [ "$ROTATE" = 1 ]; then
  [ -z "$app_id" ] || fapi0 token DELETE "/user/applications/oauth2/$app_id" >/dev/null || true
  log "creating the CI OAuth application"
  out="$(fapi token POST /user/applications/oauth2 <<<"{\"name\":\"woodpecker\",\"redirect_uris\":$redirect,\"confidential_client\":true}")"
  [ "$(printf '%s\n' "$out" | http_code)" = 201 ] || die "cannot create the OAuth application"
  body="$(printf '%s\n' "$out" | http_body)"
  env_set "$ENV_FILE" PACK_OAUTH_APP_ID "$(printf '%s' "$body" | json_get id)"
  env_set "$ENV_FILE" WOODPECKER_FORGEJO_CLIENT "$(printf '%s' "$body" | json_get client_id)"
  env_set "$ENV_FILE" WOODPECKER_FORGEJO_SECRET "$(printf '%s' "$body" | json_get client_secret)"
  rotated_oauth=1
else # keep the redirect URI in step with the public URL
  fapi token PATCH "/user/applications/oauth2/$app_id" <<<"{\"name\":\"woodpecker\",\"redirect_uris\":$redirect,\"confidential_client\":true}" >/dev/null || true
fi

# --- 4. CI ---------------------------------------------------------------------------------
log "starting the CI"
compose up -d woodpecker-server woodpecker-agent >&2
wait_healthy woodpecker-server
wait_healthy woodpecker-agent

ci_ok() { # ci_ok TOKEN: is the token accepted by the CI API?
  [ -n "$1" ] && WP_TOKEN="$1" compose exec -T -e WP_TOKEN forgejo sh -c \
    'curl -fsS -o /dev/null -H "Authorization: Bearer $WP_TOKEN" http://woodpecker-server:8000/ci/api/user' 2>/dev/null
}
wp_token="$(env_get "$ENV_FILE" PACK_WOODPECKER_TOKEN)"
if [ "$ROTATE" = 1 ] || [ "${rotated_oauth:-0}" = 1 ] || ! ci_ok "$wp_token"; then
  log "minting the CI API token (headless OAuth sign-in of the service account)"
  wp_token="$(docker run --rm --network "$PACK_NETWORK" --read-only --cap-drop ALL \
      --security-opt no-new-privileges:true -e PACK_SERVICE_USER -e PACK_SERVICE_PASSWORD \
      -v "$PACK_DIR/hooks/wp_login.py:/wp_login.py:ro" "$PYTHON_IMAGE" \
      python -I /wp_login.py "$public_url" http://forgejo:3000 http://woodpecker-server:8000)" \
    || die "cannot obtain the CI token"
  env_set "$ENV_FILE" PACK_WOODPECKER_TOKEN "$wp_token"
fi

# --- 5. hand the endpoints to the core ------------------------------------------------------
"$PACK_DIR/hooks/register-core.sh"
log "pack ready. Git: $public_url/git/   CI: $public_url/ci/ (API only in v0.1)"
