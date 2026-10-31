#!/usr/bin/env bash
# Bring up a throw-away pack (own compose project, own secrets, ONE port bound to 127.0.0.1),
# run the step-6 integration test against it, tear everything down.
#
# Needs the Cobble core network (cobble_core) and the backend dev environment (uv).
#   hooks/test-flow.sh [--keep]      --keep leaves the pack running for inspection
# Environment: COBBLE_PACK_STEP_CA, COBBLE_PACK_SKIP_STEPS (see install.sh),
#              PACK_TEST_PORT (default 18081), COBBLE_PACK_FLOW_TIMEOUT_S (default 900).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"
port="${PACK_TEST_PORT:-18081}"

export COBBLE_PACK_PROJECT="cobblepack-flow"
export COBBLE_PACK_ENV="$tmp/env"
export COBBLE_PACK_CORE_ENV="$tmp/env.pack"
export COBBLE_PACK_PUBLIC_URL="http://cobble.test:$port"
export COBBLE_PACK_COMPOSE_EXTRA="-f $here/../compose.test.yml"
export PACK_TEST_PORT="$port"

cleanup() {
  if [ "${1:-}" != "--keep" ]; then
    "$here/uninstall.sh" --purge || true
    docker network rm cobble-pack-ci >/dev/null 2>&1 || true
  else
    echo "pack left running (env: $tmp); remove with COBBLE_PACK_ENV=$tmp/env hooks/uninstall.sh --purge" >&2
  fi
}
trap 'cleanup "${1:-}"' EXIT

"$here/install.sh"
"$here/register-core.sh" --out "$tmp/env.host" \
  --forgejo-url "http://localhost:$port/git" --woodpecker-url "http://localhost:$port/ci"
set -a
# shellcheck disable=SC1091
. "$tmp/env.host"
set +a
cd "$here/../../../backend"
COBBLE_PACK_FLOW=1 uv run pytest -q -m integration tests/integration/test_pack_flow.py
