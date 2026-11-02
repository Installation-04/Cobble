#!/usr/bin/env bash
# Before the preview service is removed: removes the demo containers and images it started (they
# live outside the module's compose project, so removing the project would leave them running).
# Best effort throughout: the platform removes the module whatever happens here.
set -euo pipefail

log() { printf '[preview] %s\n' "$*" >&2; }

docker stop "cobble-${COBBLE_MODULE_ID:-preview}-preview-service" >/dev/null 2>&1 || true
# The service labels everything it starts (cobble.preview=1): containers, then the images it built.
ids="$(docker ps -aq --filter label=cobble.preview=1 2>/dev/null || true)"
# shellcheck disable=SC2086  # the ids are space separated on purpose
[ -z "$ids" ] || docker rm -f $ids >/dev/null 2>&1 || true
images="$(docker images -q --filter label=cobble.preview=1 2>/dev/null || true)"
# shellcheck disable=SC2086
[ -z "$images" ] || docker rmi -f $images >/dev/null 2>&1 || true
log "demo containers and images removed"
