#!/usr/bin/env bash
# Before the agent service is removed: stops the agent containers it started (they live outside
# the module's compose project, so removing the project would leave them running). The runner
# image is left in place. Best effort throughout: the platform removes the module whatever
# happens here.
set -euo pipefail

log() { printf '[aider] %s\n' "$*" >&2; }

docker stop "cobble-${COBBLE_MODULE_ID:-aider}-agent-service" >/dev/null 2>&1 || true
# Agent containers carry the network of this module's agents network.
network="cobble-${COBBLE_MODULE_ID:-aider}-agents"
ids="$(docker ps -aq --filter "network=$network" 2>/dev/null || true)"
# shellcheck disable=SC2086  # the ids are space separated on purpose
[ -z "$ids" ] || docker rm -f $ids >/dev/null 2>&1 || true
log "agent containers removed"
