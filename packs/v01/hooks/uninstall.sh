#!/usr/bin/env bash
# Stop and remove the pack containers and networks. Repositories and CI history are kept
# (named volumes) unless --purge is given, which also deletes volumes, .env and .env.pack.
#
# Usage: hooks/uninstall.sh [--purge]
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

case "${1:-}" in
  --purge) compose down --volumes --remove-orphans >&2
           rm -f "$ENV_FILE" "$CORE_ENV_FILE"
           log "pack removed, data and secrets deleted" ;;
  "") compose down --remove-orphans >&2
      "$PACK_DIR/hooks/unlink.sh"
      log "pack stopped; data kept (use --purge to delete it)" ;;
  *) die "usage: uninstall.sh [--purge]" ;;
esac
