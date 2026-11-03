#!/usr/bin/env bash
# Fetches the models the chosen flavour serves (COBBLE_LLM_PULL, comma separated) so that the
# first request does not wait for a download. Idempotent: a model already present is not fetched
# again. A failed download fails the install (the platform rolls it back): a backend that serves
# no model is not useful, and the cause (no network, no disk) is better known now than later.
set -euo pipefail

CONTAINER="cobble-${COBBLE_MODULE_ID}-ollama"
log() { printf '[ollama] %s\n' "$*" >&2; }

IFS=',' read -r -a models <<<"${COBBLE_LLM_PULL:-}"
for model in "${models[@]}"; do
  [ -n "$model" ] || continue
  if docker exec "$CONTAINER" ollama show "$model" >/dev/null 2>&1; then
    log "$model is already there"
    continue
  fi
  log "fetching $model (this can take several minutes)"
  docker exec "$CONTAINER" ollama pull "$model" >/dev/null || { log "cannot fetch $model"; exit 1; }
done
log "models ready"
