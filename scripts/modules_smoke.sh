#!/usr/bin/env bash
# Installs a catalogue module through the real module-manager, checks it end to end and removes
# it. Needs a running stack started with the `modules` profile (make dev-modules).
#   scripts/modules_smoke.sh [forgejo]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
module="${1:-forgejo}"
COMPOSE=(docker compose -f core/compose.yml ${COMPOSE_FLAGS:-} --profile modules)
port="$(sed -n 's/^COBBLE_HTTP_PORT=//p' core/.env)"
base="http://localhost:${port:-80}"
mm() { "${COMPOSE[@]}" exec -T module-manager python - "$@" <scripts/module_client.py; }
fail() { echo "FAIL: $*" >&2; exit 1; }

echo "== install $module"
out="$(mm install "$module" | tail -n 1)"
echo "$out" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)["state"]=="done" else 1)' \
  || fail "install did not finish: $out"

echo "== the core can reach it"
conn="$(mm connections)"
token="$(echo "$conn" | python3 -c 'import json,sys; print(json.load(sys.stdin)["connections"]["'"$module"'"]["secrets"].get("api_token",""))')"
[ -n "$token" ] || fail "no api_token for the core"
# The secret must not appear in what the manager logs.
if "${COMPOSE[@]}" logs module-manager 2>&1 | grep -qF "$token"; then fail "token found in the manager logs"; fi

echo "== routed by Caddy, no host port"
curl -fsS -o /dev/null "$base/git/api/healthz" || fail "route /git does not answer"
curl -fsS -H "Authorization: token $token" "$base/git/api/v1/user" | grep -q cobble-bot || fail "token rejected"
if docker ps --format '{{.Names}} {{.Ports}}' | grep "^cobble-$module" | grep -q -- '->'; then fail "a host port is published"; fi

echo "== uninstall"
mm uninstall "$module" | tail -n 1 | grep -q '"state": "done"' || fail "uninstall failed"
[ -z "$(docker ps -aq --filter "name=cobble-$module")" ] || fail "containers left"
[ -z "$(docker volume ls -q --filter "name=cobble-$module")" ] || fail "volumes left"
[ -z "$("${COMPOSE[@]}" exec -T caddy ls /etc/caddy/routes)" ] || fail "route left"
echo "modules smoke test passed"
