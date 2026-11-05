#!/usr/bin/env bash
# Cobble installer (Ubuntu 24.04/26.04, Debian 12/13, amd64). Run as root:
#   curl -fsSL https://raw.githubusercontent.com/Installation-04/Cobble/main/installer/install.sh | sudo bash
# Idempotent: re-running repairs or completes the install without destroying data.
# Keep this script short: heavy logic belongs in the backend, not here.
set -euo pipefail

# Where Cobble is downloaded from. COBBLE_REPO=owner/name selects a fork; the two base URLs
# are overridable so that the tests can serve fixtures from a local server.
COBBLE_REPO="${COBBLE_REPO:-Installation-04/Cobble}"
GITHUB_URL="${COBBLE_GITHUB_URL:-https://github.com}"
CODELOAD_URL="${COBBLE_CODELOAD_URL:-https://codeload.github.com}"

ORIG_ARGS=("$@")
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
fi

# --- source handling (runs before the message catalogs are available) -------------------
# Messages here are bilingual on purpose: the catalogs ship inside the tree being downloaded.

# fail EN FR: print both languages on stderr and stop.
fail() {
  printf 'ERROR: %s\nERREUR : %s\n' "$1" "$2" >&2
  exit 1
}

NO_VERIFY=0 # --no-verify: skip the SHA-256 check of a downloaded tarball (unsafe)
REF_MODE=0  # the source is a GitHub branch/tag/sha archive: no checksum exists for it

# source_url KIND [VALUE]: tarball URL of the latest release, of one release (vX.Y.Z) or of a ref.
source_url() {
  [[ "$COBBLE_REPO" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] ||
    fail "Invalid COBBLE_REPO: $COBBLE_REPO (expected owner/name)" "COBBLE_REPO invalide : $COBBLE_REPO (owner/nom attendu)"
  case "$1" in
    latest) echo "$GITHUB_URL/$COBBLE_REPO/releases/latest/download/cobble.tar.gz" ;;
    version)
      local v="$2"
      case "$v" in v*) ;; *) v="v$v" ;; esac
      [[ "$v" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-+.][0-9A-Za-z.-]+)?$ ]] ||
        fail "Invalid --version: $2 (expected vX.Y.Z)" "Valeur de --version invalide : $2 (vX.Y.Z attendu)"
      echo "$GITHUB_URL/$COBBLE_REPO/releases/download/$v/cobble.tar.gz"
      ;;
    ref)
      { [[ "$2" =~ ^[A-Za-z0-9._/-]+$ ]] && [[ "$2" != -* ]]; } ||
        fail "Invalid --ref: $2" "Valeur de --ref invalide : $2"
      echo "$CODELOAD_URL/$COBBLE_REPO/tar.gz/$2"
      ;;
  esac
}

# pick_source SOURCE VERSION REF: print the source to use (empty when none was asked for).
# Sets REF_MODE when the source is a ref archive. At most one of the three may be given.
pick_source() {
  local n=0
  [ -z "$1" ] || n=$((n + 1))
  [ -z "$2" ] || n=$((n + 1))
  [ -z "$3" ] || n=$((n + 1))
  [ "$n" -le 1 ] || fail "Use only one of --source, --version, --ref" "Utilisez un seul parmi --source, --version, --ref"
  if [ -n "$2" ]; then
    source_url version "$2"
  elif [ -n "$3" ]; then
    source_url ref "$3"
  else
    echo "$1"
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# fetch_tarball URL DEST: download to a temp file, verify its SHA-256 (<URL>.sha256), extract.
# Never streams a download into tar: nothing is unpacked before the checksum matched.
fetch_tarball() {
  local url="$1" dest="$2" tmp code rc=0 expected actual
  tmp="$(mktemp -d)"
  code="$(curl -fsSL -o "$tmp/cobble.tar.gz" -w '%{http_code}' "$url")" || rc=$?
  if [ "$rc" -ne 0 ]; then
    rm -rf "$tmp"
    if [ "$code" = 404 ] && [[ "$url" == */releases/latest/download/* ]]; then
      fail "No Cobble release is published yet ($url). Install from the main branch instead (not a verified release): install.sh --ref main" \
        "Aucune version de Cobble n’est encore publiée ($url). Installez plutôt depuis la branche main (version non vérifiée) : install.sh --ref main"
    elif [ "$code" = 404 ]; then
      fail "Not found (404): $url. Check the version or the repository name." \
        "Introuvable (404) : $url. Vérifiez la version ou le nom du dépôt."
    fi
    fail "Download failed: $url" "Échec du téléchargement : $url"
  fi
  if [ "$REF_MODE" = 1 ]; then
    printf 'WARNING: %s is NOT a verified release: nothing guarantees its content and the images are built from source (slow). Prefer a release.\nAVERTISSEMENT : %s n'\''est PAS une version vérifiée : rien ne garantit son contenu et les images sont construites depuis les sources (lent). Préférez une version publiée.\n' "$url" "$url" >&2
  elif [ "$NO_VERIFY" = 1 ]; then
    printf 'WARNING: --no-verify: the SHA-256 of %s is NOT checked (unsafe).\nAVERTISSEMENT : --no-verify : le SHA-256 de %s n'\''est PAS vérifié (risqué).\n' "$url" "$url" >&2
  else
    rc=0
    curl -fsSL -o "$tmp/cobble.tar.gz.sha256" "$url.sha256" || rc=$?
    if [ "$rc" -ne 0 ]; then
      rm -rf "$tmp"
      fail "Checksum file not found: $url.sha256. Refusing to install an unverified download (--no-verify only if you accept the risk)." \
        "Fichier de somme de contrôle introuvable : $url.sha256. Refus d’installer un téléchargement non vérifié (--no-verify seulement si vous acceptez le risque)."
    fi
    expected="$(awk 'NR==1 {print tolower($1)}' "$tmp/cobble.tar.gz.sha256")"
    if ! [[ "$expected" =~ ^[0-9a-f]{64}$ ]]; then
      rm -rf "$tmp"
      fail "Malformed checksum file: $url.sha256" "Fichier de somme de contrôle illisible : $url.sha256"
    fi
    actual="$(sha256_of "$tmp/cobble.tar.gz")"
    if [ "$actual" != "$expected" ]; then
      rm -rf "$tmp"
      fail "SHA-256 mismatch for $url (expected $expected, got $actual). The download is corrupt or was tampered with; nothing was installed." \
        "SHA-256 différent pour $url (attendu $expected, obtenu $actual). Le téléchargement est corrompu ou altéré; rien n’a été installé."
    fi
  fi
  if ! tar -xzf "$tmp/cobble.tar.gz" --strip-components=1 -C "$dest"; then
    rm -rf "$tmp"
    fail "Could not extract $url" "Impossible d’extraire $url"
  fi
  rm -rf "$tmp"
}

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
        fetch_tarball "$src" "$dest"
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
  elif [ -n "${COBBLE_TARBALL_URL:-}" ]; then
    echo "$COBBLE_TARBALL_URL"
  else
    source_url latest
  fi
}

# Piped (curl | bash) or copied alone: fetch the source first, then continue from it,
# because the message catalogs and lib.sh ship with the source tree.
if [ -z "$SCRIPT_DIR" ] || [ ! -f "$SCRIPT_DIR/lib.sh" ]; then
  boot_src="" boot_version="" boot_ref="" boot_args=()
  for ((i = 0; i < ${#ORIG_ARGS[@]}; i++)); do
    a="${ORIG_ARGS[$i]}"
    case "$a" in
      --source=*) boot_src="${a#--source=}" ;;
      --version=*) boot_version="${a#--version=}" ;;
      --ref=*) boot_ref="${a#--ref=}" ;;
      --source | --version | --ref)
        [ "$((i + 1))" -lt "${#ORIG_ARGS[@]}" ] || fail "Option $a needs a value" "L’option $a attend une valeur"
        case "$a" in
          --source) boot_src="${ORIG_ARGS[$((i + 1))]}" ;;
          --version) boot_version="${ORIG_ARGS[$((i + 1))]}" ;;
          --ref) boot_ref="${ORIG_ARGS[$((i + 1))]}" ;;
        esac
        i=$((i + 1))
        ;;
      --no-verify)
        NO_VERIFY=1
        boot_args+=("$a")
        ;;
      *) boot_args+=("$a") ;;
    esac
  done
  [ -z "$boot_ref" ] || REF_MODE=1
  boot_src="$(pick_source "$boot_src" "$boot_version" "$boot_ref")"
  [ -n "$boot_src" ] || boot_src="$(default_source)"
  boot_dir="$(mktemp -d)"
  fetch_source "$boot_src" "$boot_dir/src" || fail "Download failed: $boot_src" "Échec du téléchargement : $boot_src"
  [ -f "$boot_dir/src/installer/install.sh" ] || fail "Invalid source: $boot_src" "Source invalide : $boot_src"
  exec bash "$boot_dir/src/installer/install.sh" "${boot_args[@]}" --source "$boot_dir/src"
fi

# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

# --- defaults and argument parsing -------------------------------------------------------

DIR="${COBBLE_DIR:-/opt/cobble}"
SOURCE=""
VERSION_ARG=""
REF_ARG=""
LATEST_ARG=0
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
    --no-verify) NO_VERIFY=1 ;;
    --latest) LATEST_ARG=1 ;;
    --dir | --lang | --source | --version | --ref | --gpu)
      [ $# -ge 2 ] || die usage_error "$1"
      case "$1" in
        --dir) DIR="$2" ;;
        --lang) LANG_ARG="$2" ;;
        --source) SOURCE="$2" ;;
        --version) VERSION_ARG="$2" ;;
        --ref) REF_ARG="$2" ;;
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
if [ "$LATEST_ARG" = 1 ]; then
  [ -z "$SOURCE" ] || fail "Use only one of --source, --version, --ref, --latest" "Utilisez un seul parmi --source, --version, --ref, --latest"
  SOURCE="$(source_url latest)"
fi
[ -z "$REF_ARG" ] || REF_MODE=1
SOURCE="$(pick_source "$SOURCE" "$VERSION_ARG" "$REF_ARG")"
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
  OS_ID="" OS_VERSION="" OS_CODENAME=""
  if [ -r "$OS_RELEASE" ]; then
    # shellcheck source=/dev/null
    OS_ID="$(. "$OS_RELEASE" && echo "${ID:-}")"
    # shellcheck source=/dev/null
    OS_VERSION="$(. "$OS_RELEASE" && echo "${VERSION_ID:-}")"
    # shellcheck source=/dev/null
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
  for c in curl tar ss; do
    command -v "$c" >/dev/null 2>&1 || missing+=("${c/ss/iproute2}")
  done
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

env_replace() { # KEY VALUE: set a value that is derived from this installation (not a secret).
  local f="$DIR/.env" tmp
  if ! grep -q "^$1=" "$f"; then
    printf '%s=%s\n' "$1" "$2" >>"$f"
    return
  fi
  tmp="$(mktemp "$f.XXXXXX")"
  # In place, so that an unchanged value leaves the file byte for byte as it was.
  awk -v key="$1" -v value="$2" 'index($0, key "=") == 1 { print key "=" value; next } { print }' "$f" >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$f"
}

# What the module-manager needs. The token is a secret (kept across runs); the rest is derived
# from this installation and refreshed on every run so that a moved or rebuilt tree stays right.
write_module_settings() {
  local socket="${COBBLE_DOCKER_SOCKET:-/var/run/docker.sock}" gid
  env_append MODULE_MANAGER_TOKEN "$(rand_hex)$(rand_hex)"
  # The module-manager is part of every start (docker compose reads COMPOSE_PROFILES from the
  # env file), including the systemd unit and `cobble status`.
  env_append COMPOSE_PROFILES modules
  # The catalogue is mounted at the same absolute path inside the module-manager: the Docker
  # daemon resolves the bind mounts of the modules on the host.
  env_replace COBBLE_CATALOG_DIR "$DIR/src/catalog"
  gid="$(stat -c %g "$socket" 2>/dev/null || true)"
  if [ -n "$gid" ]; then env_replace DOCKER_GID "$gid"; fi
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
  env_append RUN_TOKEN_SECRET "$(rand_hex)$(rand_hex)"
  local suffix=""
  [ "$port" = 80 ] || suffix=":$port"
  env_append COBBLE_PUBLIC_URL "http://$(primary_ip)$suffix"
  write_module_settings
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
  # Release trees carry compose.release.yml: published images are pulled, nothing is built.
  local build=(--build)
  if release_override "$DIR"; then build=(); fi
  "${COMPOSE[@]}" up -d "${build[@]}" --wait || {
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
  cmd="$cmd --env-file $DIR/.env -f $DIR/src/core/compose.yml"
  if release_override "$DIR"; then cmd="$cmd -f $DIR/src/core/compose.release.yml"; fi
  cmd="$cmd -f $DIR/compose.install.yml"
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
  printf '    %s\n' "$(msg done_url_host "http://$(uname -n)$suffix")"
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
