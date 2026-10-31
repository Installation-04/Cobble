#!/usr/bin/env bash
# Disconnect the core from the pack: removes .env.pack. The pack keeps running; re-run
# hooks/register-core.sh to link it again.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
rm -f "$CORE_ENV_FILE"
log "core unlinked ($CORE_ENV_FILE removed)"
