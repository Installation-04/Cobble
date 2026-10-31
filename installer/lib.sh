#!/usr/bin/env bash
# Shared helpers for install.sh and the cobble CLI. Sourced, never executed.
# User-facing text lives in messages.<lang>.sh (identical keys, see tests/run.sh).

# shellcheck disable=SC2034
COBBLE_VERSION="0.1.0-dev"

# env_get KEY FILE: last value of KEY in an env file (empty if missing).
env_get() {
  [ -f "$2" ] || return 0
  sed -n "s/^$1=//p" "$2" | tail -n 1
}

# state_get KEY FILE: value of a flat "key": "value" entry of state.json.
state_get() {
  [ -f "$2" ] || return 0
  sed -n "s/^ *\"$1\": *\"\(.*\)\",\{0,1\}$/\1/p" "$2" | head -n 1
}

# detect_lang [EXPLICIT] [ENV_FILE]: fr or en.
detect_lang() {
  local l="${1:-${COBBLE_LANG:-}}"
  if [ -z "$l" ] && [ -n "${2:-}" ]; then l="$(env_get COBBLE_LANG "$2")"; fi
  [ -n "$l" ] || l="${LANG:-}"
  case "$l" in
    fr*) echo fr ;;
    *) echo en ;;
  esac
}

# load_messages DIR LANG: English first, then the requested language on top.
load_messages() {
  # shellcheck source=messages.en.sh
  . "$1/messages.en.sh"
  if [ "$2" != "en" ] && [ -f "$1/messages.$2.sh" ]; then
    # shellcheck source=messages.fr.sh
    . "$1/messages.$2.sh"
  fi
}

# msg KEY [ARGS...]: formatted catalog message (no trailing newline).
msg() {
  local key="M_$1" fmt
  shift
  fmt="${!key:-$key}"
  # shellcheck disable=SC2059
  printf -- "$fmt" "$@"
}

info() { printf '==> %s\n' "$(msg "$@")"; }
warn() { printf 'WARN: %s\n' "$(msg "$@")" >&2; }
die() {
  printf 'ERROR: %s\n' "$(msg "$@")" >&2
  exit 1
}

# set_compose DIR: build the COMPOSE array for an installed tree.
set_compose() {
  COMPOSE=(docker compose)
  if [ -n "${COBBLE_COMPOSE_PROJECT:-}" ]; then COMPOSE+=(-p "$COBBLE_COMPOSE_PROJECT"); fi
  COMPOSE+=(--env-file "$1/.env" -f "$1/src/core/compose.yml")
  if [ -f "$1/compose.install.yml" ]; then COMPOSE+=(-f "$1/compose.install.yml"); fi
}

# systemd_available: true when systemd is PID 1 (override: COBBLE_SYSTEMD=0|1).
systemd_available() {
  case "${COBBLE_SYSTEMD:-auto}" in
    1) return 0 ;;
    0) return 1 ;;
  esac
  [ -d /run/systemd/system ]
}
