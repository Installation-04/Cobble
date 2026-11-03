#!/usr/bin/env bash
# Before the agent service starts: takes the Git server's address and API token from the peer
# (Git is already running: this module requires it) and hands them to the platform as this
# module's own secrets, and pulls the runner image the service starts for every task (it is not
# a compose service, so `up` would not fetch it). Idempotent.
set -euo pipefail

: "${COBBLE_PEER_GIT_HOST:?}" "${COBBLE_PEER_GIT_PORT:?}" "${COBBLE_PEER_GIT_SECRET_API_TOKEN:?}"

log() { printf '[aider] %s\n' "$*" >&2; }

printf '::secret::forgejo_url=http://%s:%s\n' "$COBBLE_PEER_GIT_HOST" "$COBBLE_PEER_GIT_PORT"
printf '::secret::forgejo_token=%s\n' "$COBBLE_PEER_GIT_SECRET_API_TOKEN"

# The runner image is the one the compose file names: a single place to pin it.
compose="$(dirname "${BASH_SOURCE[0]}")/../compose.yml"
runner="$(sed -n 's/^ *COBBLE_AGENT_RUNNER_IMAGE: *//p' "$compose" | head -n 1)"
[ -n "$runner" ] || { log "no runner image in the compose file"; exit 1; }
log "pulling the runner image (about 2 GB the first time)"
docker pull --quiet "$runner" >/dev/null
log "runner image ready"
