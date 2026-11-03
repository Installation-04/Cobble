#!/usr/bin/env bash
# Before the preview service starts: takes the Git server's address and API token from the peer
# (Git is already running: this module requires it) and hands them to the platform as this
# module's own secrets. Idempotent.
set -euo pipefail

: "${COBBLE_PEER_GIT_HOST:?}" "${COBBLE_PEER_GIT_PORT:?}" "${COBBLE_PEER_GIT_SECRET_API_TOKEN:?}"

printf '::secret::forgejo_url=http://%s:%s\n' "$COBBLE_PEER_GIT_HOST" "$COBBLE_PEER_GIT_PORT"
printf '::secret::forgejo_token=%s\n' "$COBBLE_PEER_GIT_SECRET_API_TOKEN"
