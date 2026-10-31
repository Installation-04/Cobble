#!/usr/bin/env bash
# Cobble installer (Ubuntu 24.04/26.04, Debian 12/13, amd64). Run as root:
#   curl -fsSL https://<domain>/install.sh | sudo bash
# Idempotent: re-running repairs or completes the install without destroying data.
# Keep this script short: heavy logic belongs in the backend, not here.
set -euo pipefail

# PLACEHOLDER: replace with the real release tarball URL once releases are published.
DEFAULT_TARBALL_URL="https://example.invalid/cobble/releases/latest/cobble.tar.gz"

ORIG_ARGS=("$@")
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
fi

# --- source handling (runs before the message catalogs are available) -------------------

# fetch_source SRC DEST: SRC is a directory, a git URL or a tarball (URL or file).
fetch_source() {
  local src="$1" dest="$2"
  mkdir -p "$dest"
  if [ -d "$src" ]; then
    tar -C "$src" --exclude=.git --exclude=node_modules --exclude=.venv --exclude=__pycache__ \
      --exclude=.env --exclude=.mypy_cache --exclude=.ruff_cache --exclude=.pytest_cache \
      --exclude=./ui/dist -cf - . | tar -C "$dest" -xf -
  else
    case "$src" in
      git@* | git+* | ssh://* | *.git)
        git clone --depth 1 "${src#git+}" "$dest" && rm -rf "$dest/.git"
        ;;
      http://* | https://*)
        curl -fsSL "$src" | tar -xz --strip-components=1 -C "$dest"
        ;;
      *)
        tar -xzf "$src" --strip-components=1 -C "$dest"
        ;;
    esac
  fi
}

default_source() {
  if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../core/compose.yml" ]; then
    (cd "$SCRIPT_DIR/.." && pwd)
  else
    echo "${COBBLE_TARBALL_URL:-$DEFAULT_TARBALL_URL}"
  fi
}

# Piped (curl | bash) or copied alone: fetch the source first, then continue from it,
# because the message catalogs and lib.sh ship with the source tree.
if [ -z "$SCRIPT_DIR" ] || [ ! -f "$SCRIPT_DIR/lib.sh" ]; then
  boot_src=""
  for ((i = 0; i < ${#ORIG_ARGS[@]}; i++)); do
    case "${ORIG_ARGS[$i]}" in
      --source=*) boot_src="${ORIG_ARGS[$i]#--source=}" ;;
      --source) boot_src="${ORIG_ARGS[$((i + 1))]:-}" ;;
    esac
  done
  [ -n "$boot_src" ] || boot_src="$(default_source)"
  boot_dir="$(mktemp -d)"
  fetch_source "$boot_src" "$boot_dir/src" || {
    echo "Download failed / Echec du telechargement: $boot_src" >&2
    exit 1
  }
  [ -f "$boot_dir/src/installer/install.sh" ] || {
    echo "Invalid source / Source invalide: $boot_src" >&2
    exit 1
  }
  exec bash "$boot_dir/src/installer/install.sh" "${ORIG_ARGS[@]}" --source "$boot_dir/src"
fi

# shellcheck source=installer/lib.sh
. "$SCRIPT_DIR/lib.sh"

# --- defaults and argument parsing -------------------------------------------------------

DIR="${COBBLE_DIR:-/opt/cobble}"
SOURCE=""
GPU_MODE="auto"
LANG_ARG=""
ASSUME_YES=0
SKIP_CHECKS="${COBBLE_SKIP_CHECKS:-0}"
OS_RELEASE="${COBBLE_OS_RELEASE:-/etc/os-release}"
BIN_DIR="${COBBLE_BIN_DIR:-/usr/local/bin}"
UNIT_DIR="${COBBLE_UNIT_DIR:-/etc/systemd/system}"
LOG_FILE="${COBBLE_LOG_FILE:-/var/log/cobble-install.log}"
MIN_CPUS="${COBBLE_MIN_CPUS:-2}"
MIN_RAM_KB="${COBBLE_MIN_RAM_KB:-3600000}" # "4 GB" VMs report about 3.8 GB
MIN_DISK_GB="${COBBLE_MIN_DISK_GB:-40}"

LANG_CODE="$(detect_lang "")"
load_messages "$SCRIPT_DIR" "$LANG_CODE"

while [ $# -gt 0 ]; do
  case "$1" in
    --*=*) set -- "${1%%=*}" "${1#*=}" "${@:2}" ;;
  esac
  case "$1" in
    -h | --help)
      printf '%s\n' "$(msg help)"
      exit 0
      ;;
    -y | --yes) ASSUME_YES=1 ;;
    --skip-checks) SKIP_CHECKS=1 ;;
    --dir | --lang | --source | --gpu)
      [ $# -ge 2 ] || die usage_error "$1"
      case "$1" in
        --dir) DIR="$2" ;;
        --lang) LANG_ARG="$2" ;;
        --source) SOURCE="$2" ;;
        --gpu) GPU_MODE="$2" ;;
      esac
      shift
      ;;
    *) die usage_error "$1" ;;
  esac
  shift
done

case "$LANG_ARG" in
  "" | fr | en) ;;
  *) die lang_invalid "$LANG_ARG" ;;
esac
case "$GPU_MODE" in
  auto | nvidia | amd | none) ;;
  *) die gpu_invalid "$GPU_MODE" ;;
esac
case "$DIR" in
  /*) ;;
  *) die dir_invalid "$DIR" ;;
esac
if [ -n "$LANG_ARG" ]; then
  LANG_CODE="$LANG_ARG"
else
  LANG_CODE="$(detect_lang "" "$DIR/.env")"
fi
load_messages "$SCRIPT_DIR" "$LANG_CODE"
[ -n "$SOURCE" ] || SOURCE="$(default_source)"

# --- logging -----------------------------------------------------------------------------

if mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null && : >>"$LOG_FILE" 2>/dev/null; then
  exec > >(tee -a "$LOG_FILE") 2>&1
  printf '\n--- cobble install %s ---\n' "$(date -u +%FT%TZ)"
fi
export DEBIAN_FRONTEND=noninteractive

# --- steps -------------------------------------------------------------------------------

step_done() { [ -f "$DIR/.steps/$1" ]; }
step_mark() {
  mkdir -p "$DIR/.steps"
  date -u +%FT%TZ >"$DIR/.steps/$1"
}

require_root() {
  [ "$(id -u)" -eq 0 ] || [ "${COBBLE_ALLOW_NONROOT:-0}" = 1 ] || die need_root
}

check_os() {
  OS_ID="" OS_VERSION=""
  if [ -r "$OS_RELEASE" ]; then
    OS_ID="$(. "$OS_RELEASE" && echo "${ID:-}")"
    OS_VERSION="$(. "$OS_RELEASE" && echo "${VERSION_ID:-}")"
    OS_CODENAME="$(. "$OS_RELEASE" && echo "${VERSION_CODENAME:-}")"
  fi
  case "$OS_ID:$OS_VERSION" in
    ubuntu:24.04 | ubuntu:26.04 | debian:12 | debian:13) info os_ok "$OS_ID $OS_VERSION" ;;
    *) die os_unsupported "${OS_ID:-?} ${OS_VERSION:-?}" ;;
  esac
}

check_arch() {
  local arch="${COBBLE_ARCH:-$(uname -m)}"
  case "$arch" in
    x86_64 | amd64) ARCH=amd64 ;;
    aarch64 | arm64) die arch_arm64 ;;
    *) die arch_unsupported "$arch" ;;
  esac
}

ensure_base_packages() {
  local missing=() c
  for c in curl tar; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
  if [ "${#missing[@]}" -gt 0 ]; then
    apt-get update -qq && apt-get install -y -qq ca-certificates "${missing[@]}"
  fi
}

# existing_ancestor PATH: nearest existing directory (df needs one).
existing_ancestor() {
  local p="$1"
  while [ ! -d "$p" ] && [ "$p" != "/" ]; do p="$(dirname "$p")"; done
  echo "$p"
}

port_in_use() { command -v ss >/dev/null 2>&1 && ss -ltnH "( sport = :$1 )" 2>/dev/null | grep -q .; }

stack_is_ours() {
  [ -f "$DIR/.env" ] && [ -f "$DIR/src/core/compose.yml" ] && command -v docker >/dev/null 2>&1 || return 1
  set_compose "$DIR"
  "${COMPOSE[@]}" ps -q caddy 2>/dev/null | grep -q .
}

check_resources() {
  local cpus ram_kb disk_kb
  cpus="$(nproc)"
  [ "$cpus" -ge "$MIN_CPUS" ] || die cpu_low "$cpus" "$MIN_CPUS"
  ram_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
  [ "$ram_kb" -ge "$MIN_RAM_KB" ] || die ram_low "$((ram_kb / 1024))"
  disk_kb="$(df -Pk "$(existing_ancestor "$DIR")" | awk 'NR==2 {print $4}')"
  [ "$disk_kb" -ge $((MIN_DISK_GB * 1024 * 1024)) ] || die disk_low "$((disk_kb / 1024 / 1024))" "$MIN_DISK_GB"
  if ! stack_is_ours; then
    if port_in_use "${COBBLE_HTTP_PORT:-80}"; then die port_busy "${COBBLE_HTTP_PORT:-80}"; fi
    if port_in_use 443; then warn port_busy_443; fi
  fi
}

check_internet() {
  curl -fsS -o /dev/null --max-time 15 https://download.docker.com/linux/debian/gpg || die no_internet
}

warn_lxc() {
  local virt=""
  if command -v systemd-detect-virt >/dev/null 2>&1; then virt="$(systemd-detect-virt -c 2>/dev/null || true)"; fi
  if [ "$virt" = lxc ] || grep -qa 'container=lxc' /proc/1/environ 2>/dev/null; then warn lxc_detected; fi
}

confirm_install() {
  [ "$ASSUME_YES" = 1 ] && return 0
  [ -r /dev/tty ] || return 0
  local answer=""
  printf '%s [y/N] ' "$(msg confirm_install "$DIR")" >/dev/tty
  read -r answer </dev/tty || true
  case "$answer" in
    y | Y | yes | YES | o | O | oui) ;;
    *) die aborted ;;
  esac
}

docker_major() { docker version --format '{{.Server.Version}}' 2>/dev/null | cut -d. -f1; }

install_docker_engine() {
  info docker_installing
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$OS_ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
    "$ARCH" "$OS_ID" "$OS_CODENAME" >/etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  if systemd_available; then systemctl enable --now docker; fi
}

ensure_docker() {
  local major
  if command -v docker >/dev/null 2>&1; then
    major="$(docker_major)"
    if [ -z "$major" ] && systemd_available; then
      systemctl start docker 2>/dev/null || true
      major="$(docker_major)"
    fi
    if [ -n "$major" ] && [ "$major" -ge 24 ] && docker compose version >/dev/null 2>&1; then
      info docker_reuse "$major"
      return 0
    fi
    die docker_unusable "${major:-?}"
  fi
  install_docker_engine
  docker compose version >/dev/null 2>&1 || die docker_broken
  step_mark docker
}

# GPU: detect and record only (v0.1 has no GPU module). Never fails the install.
detect_gpu() {
  GPU=none GPU_TOOLKIT=n/a
  case "$GPU_MODE" in
    nvidia | amd) GPU="$GPU_MODE" ;;
    auto)
      if command -v nvidia-smi >/dev/null 2>&1 || { command -v lspci >/dev/null 2>&1 && lspci 2>/dev/null | grep -qi nvidia; }; then
        GPU=nvidia
      elif [ -e /dev/kfd ] && [ -d /dev/dri ]; then
        GPU=amd
      fi
      ;;
  esac
  if [ "$GPU" = none ]; then
    info gpu_none
    return 0
  fi
  info gpu_detected "$GPU"
  if [ "$GPU" = nvidia ]; then
    GPU_TOOLKIT=failed
    if step_done gpu-toolkit; then
      GPU_TOOLKIT=ok
    elif nvidia_toolkit; then
      GPU_TOOLKIT=ok
      step_mark gpu-toolkit
      info gpu_toolkit_ok
    else
      warn gpu_toolkit_failed
    fi
  fi
}

nvidia_toolkit() {
  nvidia-smi -L >/dev/null 2>&1 || {
    warn gpu_nvidia_nodriver
    return 1
  }
  if ! command -v nvidia-ctk >/dev/null 2>&1; then
    info gpu_toolkit_installing
    local keyring=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    apt-get install -y -qq gnupg || return 1
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor --yes -o "$keyring" || return 1
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
      sed "s#deb https://#deb [signed-by=$keyring] https://#g" >/etc/apt/sources.list.d/nvidia-container-toolkit.list || return 1
    apt-get update -qq && apt-get install -y -qq nvidia-container-toolkit || return 1
  fi
  nvidia-ctk runtime configure --runtime=docker || return 1
  if systemd_available; then systemctl restart docker || return 1; fi
  docker run --rm --gpus all debian:12-slim nvidia-smi -L >/dev/null || return 1
}

sync_source() {
  local stage="$DIR/src.new" same=0
  if [ -d "$SOURCE" ] && [ -d "$DIR/src" ] && [ "$(cd "$SOURCE" && pwd -P)" = "$(cd "$DIR/src" && pwd -P)" ]; then same=1; fi
  if [ "$same" = 1 ]; then return 0; fi
  info source_fetching "$SOURCE"
  rm -rf "$stage"
  fetch_source "$SOURCE" "$stage" || die source_failed "$SOURCE"
  [ -f "$stage/core/compose.yml" ] || die source_bad "$SOURCE"
  if [ -d "$DIR/src" ]; then
    rm -rf "$DIR/src.old"
    mv "$DIR/src" "$DIR/src.old"
  fi
  mv "$stage" "$DIR/src"
  rm -rf "$DIR/src.old"
}

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 16; else od -An -N16 -tx1 /dev/urandom | tr -d ' \n'; fi
}

primary_ip() {
  local ip="${COBBLE_PRIMARY_IP:-}"
  [ -n "$ip" ] || ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n 1)"
  [ -n "$ip" ] || ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "${ip:-127.0.0.1}"
}

env_append() { # KEY VALUE: add only when the key is absent (never overwrites).
  grep -q "^$1=" "$DIR/.env" || printf '%s=%s\n' "$1" "$2" >>"$DIR/.env"
}

write_env() {
  local f="$DIR/.env" port="${COBBLE_HTTP_PORT:-80}"
  if [ -f "$f" ]; then
    chmod 600 "$f"
    info env_kept
  else
    (
      umask 077
      set -o noclobber
      {
        echo "POSTGRES_PASSWORD=$(rand_hex)"
        echo "REDIS_PASSWORD=$(rand_hex)"
        echo "LITELLM_MASTER_KEY=sk-cobble-$(rand_hex)"
      } >"$f"
    )
    info env_created
  fi
  port="$(env_get COBBLE_HTTP_PORT "$f")"
  port="${port:-${COBBLE_HTTP_PORT:-80}}"
  env_append COBBLE_HTTP_PORT "$port"
  env_append COBBLE_LANG "$LANG_CODE"
  local suffix=""
  [ "$port" = 80 ] || suffix=":$port"
  env_append COBBLE_PUBLIC_URL "http://$(primary_ip)$suffix"
  HTTP_PORT="$port"
  PUBLIC_URL="$(env_get COBBLE_PUBLIC_URL "$f")"
}

# The core compose file does not forward COBBLE_PUBLIC_URL to the api container; this
# generated override does, so the activation link is built from the real address.
write_override() {
  cat >"$DIR/compose.install.yml" <<'YAML'
# Generated by install.sh (rewritten on every run). Do not edit.
services:
  api:
    environment:
      COBBLE_PUBLIC_URL: ${COBBLE_PUBLIC_URL}
YAML
}

write_state() {
  local installed_at
  installed_at="$(state_get installed_at "$DIR/state.json")"
  installed_at="${installed_at:-$(date -u +%FT%TZ)}"
  cat >"$DIR/state.json.tmp" <<EOF
{
  "version": "$COBBLE_VERSION",
  "installed_at": "$installed_at",
  "updated_at": "$(date -u +%FT%TZ)",
  "dir": "$DIR",
  "os": "$OS_ID $OS_VERSION",
  "arch": "$ARCH",
  "gpu": "$GPU",
  "gpu_toolkit": "$GPU_TOOLKIT",
  "lang": "$LANG_CODE",
  "public_url": "$PUBLIC_URL"
}
EOF
  mv "$DIR/state.json.tmp" "$DIR/state.json"
}

start_core() {
  set_compose "$DIR"
  info core_starting
  "${COMPOSE[@]}" up -d --build --wait || {
    warn core_failed
    "${COMPOSE[@]}" ps || true
    exit 1
  }
}

install_unit() {
  if ! systemd_available; then
    warn systemd_skip
    return 0
  fi
  mkdir -p "$UNIT_DIR"
  local cmd
  cmd="$(command -v docker) compose"
  if [ -n "${COBBLE_COMPOSE_PROJECT:-}" ]; then cmd="$cmd -p $COBBLE_COMPOSE_PROJECT"; fi
  cmd="$cmd --env-file $DIR/.env -f $DIR/src/core/compose.yml -f $DIR/compose.install.yml"
  cat >"$UNIT_DIR/cobble.service" <<EOF
[Unit]
Description=Cobble
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$DIR
ExecStart=$cmd up -d --wait
ExecStop=$cmd down
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now cobble.service
  info unit_installed
}

open_firewall() {
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
    ufw allow "$HTTP_PORT/tcp" >/dev/null
    ufw allow 443/tcp >/dev/null
    info ufw_opened
  fi
}

install_cli() {
  mkdir -p "$BIN_DIR"
  sed "s|^DEFAULT_DIR=.*|DEFAULT_DIR=\"$DIR\"|" "$DIR/src/installer/cobble" >"$BIN_DIR/cobble.tmp"
  chmod 755 "$BIN_DIR/cobble.tmp"
  mv "$BIN_DIR/cobble.tmp" "$BIN_DIR/cobble"
  info cli_installed "$BIN_DIR/cobble"
}

print_summary() {
  local suffix="" link rc=0
  [ "$HTTP_PORT" = 80 ] || suffix=":$HTTP_PORT"
  echo
  info done_title
  printf '    %s\n' "$(msg done_url_ip "http://$(primary_ip)$suffix")"
  printf '    %s\n' "$(msg done_url_host "http://$(hostname)$suffix")"
  link="$("${COMPOSE[@]}" exec -T api python -m cobble.cli activation-link 2>/dev/null)" || rc=$?
  if [ "$rc" -eq 0 ] && [ -n "$link" ]; then
    printf '\n%s\n%s\n' "$(msg done_activation)" "$link"
  else
    printf '\n%s\n' "$(msg done_admin_exists)"
  fi
  printf '\n%s\n' "$(msg done_next)"
}

main() {
  require_root
  check_os
  check_arch
  ensure_base_packages
  if [ "$SKIP_CHECKS" != 1 ]; then
    check_resources
    check_internet
  fi
  warn_lxc
  confirm_install
  mkdir -p "$DIR"
  ensure_docker
  detect_gpu
  sync_source
  write_env
  write_override
  start_core
  install_unit
  open_firewall
  install_cli
  write_state
  print_summary
}

main
