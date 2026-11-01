#!/usr/bin/env bash
# Plain-bash tests for the installer and the cobble CLI. No root, no Docker required:
# docker/systemctl/curl/ss are replaced by stubs from tests/stubs/ placed first in PATH.
# Usage: installer/tests/run.sh [name-filter]
# shellcheck disable=SC2015
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="$(cd "$HERE/.." && pwd)"
FILTER="${1:-}"
PASS=0
FAIL=0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ok() {
  PASS=$((PASS + 1))
  printf 'PASS %s\n' "$1"
}
ko() {
  FAIL=$((FAIL + 1))
  printf 'FAIL %s: %s\n' "$1" "$2"
}

# Fresh sandbox per test: S (root dir), fake source, env for install.sh and cobble.
new_sandbox() {
  S="$TMP/$1"
  rm -rf "$S"
  mkdir -p "$S/bin" "$S/unit" "$S/src/core" "$S/src/catalog/demo"
  : >"$S/src/core/compose.yml"
  : >"$S/src/catalog/demo/manifest.yaml"
  : >"$S/docker.sock" # stands for /var/run/docker.sock: only its group matters
  cp -r "$INSTALLER" "$S/src/installer"
  rm -rf "$S/src/installer/tests"
  printf 'ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n' >"$S/os-release"
  : >"$S/stub.log"
  export STUB_LOG="$S/stub.log"
  export PATH="$HERE/stubs:$ORIG_PATH"
  export COBBLE_ALLOW_NONROOT=1 COBBLE_SYSTEMD=1 COBBLE_SKIP_CHECKS=1
  export COBBLE_OS_RELEASE="$S/os-release" COBBLE_BIN_DIR="$S/bin" COBBLE_UNIT_DIR="$S/unit"
  export COBBLE_LOG_FILE="$S/install.log" COBBLE_PRIMARY_IP=10.0.0.5 COBBLE_DIR="$S/opt"
  export COBBLE_LANG=en COBBLE_DOCKER_SOCKET="$S/docker.sock"
  unset COBBLE_ARCH COBBLE_DOCTOR_FAKE_DOWN STUB_BAD_CONTAINER STUB_BAD_EXIT STUB_MODULES_RC STUB_UNIT_DOWN STUB_NO_LISTEN STUB_NO_ADMIN_LINK
}
ORIG_PATH="$PATH"

install_sh() { bash "$INSTALLER/install.sh" --yes --source "$S/src" "$@"; }
run_cli() { bash "$INSTALLER/cobble" "$@"; }

t_catalogs_same_keys() {
  local a b
  a="$(grep -oE '^M_[a-z0-9_]+=' "$INSTALLER/messages.en.sh" | sort)"
  b="$(grep -oE '^M_[a-z0-9_]+=' "$INSTALLER/messages.fr.sh" | sort)"
  [ -n "$a" ] && [ "$a" = "$b" ] || {
    ko catalogs_same_keys "$(diff <(echo "$a") <(echo "$b") | head -5)"
    return
  }
  # every key used by the scripts exists in the catalog
  local used missing
  used="$(grep -ohE '(info|warn|die|msg|confirm) [a-z_0-9]+' "$INSTALLER/install.sh" "$INSTALLER/cobble" | awk '{print "M_"$2"="}'
    grep -ohE 'fix_[a-z_]+' "$INSTALLER/cobble" | sed 's/^/M_/;s/$/=/')"
  missing="$(echo "$used" | sort -u | comm -23 - <(echo "$a"))"
  [ -z "$missing" ] && ok catalogs_same_keys || ko catalogs_same_keys "undefined keys: $missing"
}

t_help() {
  new_sandbox help
  local out
  out="$(bash "$INSTALLER/install.sh" --help 2>&1)" && [[ "$out" == *"--dir"* && "$out" == *"--skip-checks"* ]] || {
    ko help_en "$out"
    return
  }
  out="$(COBBLE_LANG=fr bash "$INSTALLER/install.sh" --help 2>&1)" && [[ "$out" == *"Utilisation"* ]] && ok help || ko help_fr "$out"
}

t_os_gate() {
  new_sandbox os
  local out rc
  printf 'ID=fedora\nVERSION_ID="40"\n' >"$S/os-release"
  out="$(install_sh --dir "$S/opt" 2>&1)" && rc=0 || rc=$?
  [ "$rc" -eq 1 ] && [[ "$out" == *"Unsupported operating system: fedora 40"* ]] || {
    ko os_gate "rc=$rc $out"
    return
  }
  printf 'ID=ubuntu\nVERSION_ID="22.04"\n' >"$S/os-release"
  out="$(install_sh --dir "$S/opt" 2>&1)" && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || {
    ko os_gate "ubuntu 22.04 accepted"
    return
  }
  [ ! -e "$S/opt/.env" ] && ok os_gate || ko os_gate "files created before the gate"
}

t_arch_gate() {
  new_sandbox arch
  local out rc
  out="$(COBBLE_ARCH=aarch64 install_sh --dir "$S/opt" 2>&1)" && rc=0 || rc=$?
  [ "$rc" -eq 1 ] && [[ "$out" == *"arm64 is not supported yet"* ]] && ok arch_gate || ko arch_gate "rc=$rc $out"
}

t_root_gate() {
  new_sandbox root
  [ "$(id -u)" -ne 0 ] || {
    ok root_gate
    return
  }
  local rc
  COBBLE_ALLOW_NONROOT=0 install_sh --dir "$S/opt" >/dev/null 2>&1 && rc=0 || rc=$?
  [ "$rc" -eq 1 ] && ok root_gate || ko root_gate "rc=$rc"
}

t_args() {
  new_sandbox args
  local rc fail=""
  install_sh --bogus >/dev/null 2>&1 && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || fail="$fail unknown-option"
  install_sh --gpu=banana >/dev/null 2>&1 && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || fail="$fail bad-gpu"
  install_sh --lang=de >/dev/null 2>&1 && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || fail="$fail bad-lang"
  install_sh --dir relative/path >/dev/null 2>&1 && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || fail="$fail relative-dir"
  install_sh --dir >/dev/null 2>&1 && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || fail="$fail missing-value"
  install_sh --dir="$S/eq" --gpu=none --lang=en >/dev/null 2>&1 && rc=0 || rc=$?
  { [ "$rc" -eq 0 ] && [ -f "$S/eq/.env" ]; } || fail="$fail equals-form"
  [ -z "$fail" ] && ok args || ko args "$fail"
}

mode_of() { stat -c %a "$1"; }

t_install_and_rerun() {
  new_sandbox install
  local out rc env1 env2 st
  out="$(install_sh --dir "$S/opt" --gpu none 2>&1)" && rc=0 || rc=$?
  [ "$rc" -eq 0 ] || {
    ko install "rc=$rc $out"
    return
  }
  local f="$S/opt/.env"
  [ "$(mode_of "$f")" = 600 ] || ko install_env_mode "$(mode_of "$f")"
  grep -qE '^POSTGRES_PASSWORD=[0-9a-f]{32}$' "$f" && grep -qE '^REDIS_PASSWORD=[0-9a-f]{32}$' "$f" &&
    grep -qE '^LITELLM_MASTER_KEY=sk-cobble-[0-9a-f]{32}$' "$f" || ko install_env_secrets "$(cat "$f")"
  grep -q '^COBBLE_HTTP_PORT=80$' "$f" && grep -q '^COBBLE_PUBLIC_URL=http://10.0.0.5$' "$f" &&
    grep -q '^COBBLE_LANG=en$' "$f" || ko install_env_keys "$(cat "$f")"
  grep -qE '^MODULE_MANAGER_TOKEN=[0-9a-f]{64}$' "$f" && grep -q '^COMPOSE_PROFILES=modules$' "$f" &&
    grep -q "^COBBLE_CATALOG_DIR=$S/opt/src/catalog\$" "$f" && grep -q "^DOCKER_GID=$(stat -c %g "$S/docker.sock")\$" "$f" ||
    ko install_module_settings "$(cat "$f")"
  [ -f "$S/opt/src/core/compose.yml" ] && [ -x "$S/bin/cobble" ] && [ -f "$S/unit/cobble.service" ] || ko install_files "missing files"
  grep -q 'ExecStart=.* up -d --wait' "$S/unit/cobble.service" && grep -q 'ExecStop=.* down' "$S/unit/cobble.service" &&
    grep -q 'Type=oneshot' "$S/unit/cobble.service" && grep -q 'RemainAfterExit=yes' "$S/unit/cobble.service" || ko install_unit "$(cat "$S/unit/cobble.service")"
  grep -q "^DEFAULT_DIR=\"$S/opt\"" "$S/bin/cobble" || ko install_cli_dir "DEFAULT_DIR not rewritten"
  grep -q -- "--env-file $S/opt/.env -f $S/opt/src/core/compose.yml" "$STUB_LOG" || ko install_compose_flags "$(cat "$STUB_LOG")"
  grep -q '"gpu": "none"' "$S/opt/state.json" && grep -q '"os": "ubuntu 24.04"' "$S/opt/state.json" || ko install_state "$(cat "$S/opt/state.json")"
  [[ "$out" == *"http://10.0.0.5"* && "$out" == *"/activate?token="* ]] || ko install_summary "$out"
  grep -q 'enable --now cobble.service' "$STUB_LOG" || ko install_systemctl "$(cat "$STUB_LOG")"

  # Re-run: .env untouched, installs completes, installed_at preserved.
  env1="$(cksum <"$f")"
  st="$(grep installed_at "$S/opt/state.json")"
  sleep 1
  out="$(install_sh --dir "$S/opt" --gpu none 2>&1)" && rc=0 || rc=$?
  env2="$(cksum <"$f")"
  [ "$rc" -eq 0 ] && [ "$env1" = "$env2" ] && [ "$st" = "$(grep installed_at "$S/opt/state.json")" ] &&
    [[ "$out" == *"never overwritten"* ]] && [ "$(mode_of "$f")" = 600 ] && ok install_and_rerun || ko install_rerun "rc=$rc same_env=$([ "$env1" = "$env2" ] && echo y || echo n) $out"
}

t_module_settings_are_added_to_an_old_env_and_kept_afterwards() {
  new_sandbox oldenv
  mkdir -p "$S/opt"
  printf 'POSTGRES_PASSWORD=mine\nREDIS_PASSWORD=mine2\nLITELLM_MASTER_KEY=k\nCOBBLE_HTTP_PORT=8081\nCOBBLE_CATALOG_DIR=/stale/place\n' >"$S/opt/.env"
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || {
    ko module_settings_old_env "install failed"
    return
  }
  local f="$S/opt/.env" token1 token2 sum1 sum2
  token1="$(grep '^MODULE_MANAGER_TOKEN=' "$f")"
  # the token is a secret (kept); the catalogue path is derived (refreshed, in place)
  grep -q "^COBBLE_CATALOG_DIR=$S/opt/src/catalog\$" "$f" && ! grep -q '/stale/place' "$f" || {
    ko module_settings_old_env "catalogue path not refreshed: $(cat "$f")"
    return
  }
  [ "$(grep -c '^COBBLE_CATALOG_DIR=' "$f")" -eq 1 ] || {
    ko module_settings_old_env "duplicated key: $(cat "$f")"
    return
  }
  sum1="$(cksum <"$f")"
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1
  token2="$(grep '^MODULE_MANAGER_TOKEN=' "$f")"
  sum2="$(cksum <"$f")"
  [ "$token1" = "$token2" ] && [ "$sum1" = "$sum2" ] && ok module_settings_old_env || ko module_settings_old_env "token or file changed on re-run"
}

t_module_manager_is_part_of_every_start() {
  new_sandbox profile
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || {
    ko module_manager_start "install failed"
    return
  }
  # the profile is in the env file, which the unit, `cobble status` and `update` all pass
  grep -q -- "--env-file $S/opt/.env" "$S/unit/cobble.service" && grep -q '^COMPOSE_PROFILES=modules$' "$S/opt/.env" &&
    ok module_manager_start || ko module_manager_start "$(cat "$S/unit/cobble.service")"
}

t_v01_pack_notice() {
  new_sandbox v01
  local out
  out="$(install_sh --dir "$S/opt" --gpu none 2>&1)"
  [[ "$out" != *"v0.1 pack"* ]] || {
    ko v01_notice "notice shown without a pack"
    return
  }
  mkdir -p "$S/src/packs/v01"
  : >"$S/src/packs/v01/.env.pack"
  out="$(install_sh --dir "$S/opt" --gpu none 2>&1)"
  [[ "$out" == *"v0.1 pack"* && "$out" == *"cobble modules install woodpecker"* ]] && [ -f "$S/opt/src/packs/v01/.env.pack" ] ||
    { ko v01_notice "$out"; return; }
  out="$(install_sh --dir "$S/opt" --lang fr --gpu none 2>&1)"
  [[ "$out" == *"pack v0.1"* ]] && ok v01_notice || ko v01_notice_fr "$out"
}

t_existing_env_kept() {
  new_sandbox keepenv
  mkdir -p "$S/opt"
  printf 'POSTGRES_PASSWORD=mine\nREDIS_PASSWORD=mine2\nLITELLM_MASTER_KEY=k\nCOBBLE_HTTP_PORT=8081\n' >"$S/opt/.env"
  chmod 644 "$S/opt/.env"
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || {
    ko existing_env_kept "install failed"
    return
  }
  [ "$(head -n 4 "$S/opt/.env")" = "$(printf 'POSTGRES_PASSWORD=mine\nREDIS_PASSWORD=mine2\nLITELLM_MASTER_KEY=k\nCOBBLE_HTTP_PORT=8081')" ] &&
    [ "$(mode_of "$S/opt/.env")" = 600 ] && grep -q '^COBBLE_PUBLIC_URL=http://10.0.0.5:8081$' "$S/opt/.env" &&
    ok existing_env_kept || ko existing_env_kept "$(cat "$S/opt/.env")"
}

t_french_install() {
  new_sandbox fr
  local out
  out="$(install_sh --dir "$S/opt" --lang fr --gpu none 2>&1)" && [[ "$out" == *"Cobble est installé"* ]] &&
    grep -q '^COBBLE_LANG=fr$' "$S/opt/.env" && ok french_install || ko french_install "$out"
}

t_no_systemd() {
  new_sandbox nosd
  local out
  out="$(COBBLE_SYSTEMD=0 install_sh --dir "$S/opt" --gpu none 2>&1)" && [[ "$out" == *"not PID 1"* ]] &&
    [ ! -f "$S/unit/cobble.service" ] && ok no_systemd || ko no_systemd "$out"
}

t_gpu_amd_recorded() {
  new_sandbox amd
  install_sh --dir "$S/opt" --gpu amd >/dev/null 2>&1 && grep -q '"gpu": "amd"' "$S/opt/state.json" && ok gpu_amd_recorded || ko gpu_amd_recorded "$(cat "$S/opt/state.json" 2>&1)"
}

t_no_admin_link() {
  new_sandbox nolink
  local out
  out="$(STUB_NO_ADMIN_LINK=1 install_sh --dir "$S/opt" --gpu none 2>&1)" && [[ "$out" == *"cobble reset-admin"* ]] && ok no_admin_link || ko no_admin_link "$out"
}

t_doctor() {
  new_sandbox doctor
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || {
    ko doctor "install failed"
    return
  }
  local out rc fail=""
  out="$(run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 0 ] && [[ "$out" == *"OK"* && "$out" != *"FAIL"* ]]; } || fail="$fail healthy(rc=$rc: $out)"
  out="$(STUB_BAD_CONTAINER=worker run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"worker"* && "$out" == *"->"* ]]; } || fail="$fail bad-container(rc=$rc)"
  out="$(STUB_BAD_CONTAINER=worker STUB_BAD_EXIT=0 run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"worker"* ]]; } || fail="$fail stopped-cleanly(rc=$rc)"
  out="$(STUB_BAD_CONTAINER=volume-init run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"volume-init"* ]]; } || fail="$fail failed-oneshot(rc=$rc)"
  mv "$S/opt/src/catalog" "$S/opt/src/catalog.off"
  out="$(run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"modules"*"catalogue is missing or empty"* ]]; } || fail="$fail no-catalogue(rc=$rc)"
  mv "$S/opt/src/catalog.off" "$S/opt/src/catalog"
  sed -i 's/^DOCKER_GID=.*/DOCKER_GID=4242/' "$S/opt/.env"
  out="$(run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"docker-group"*"4242"* ]]; } || fail="$fail docker-group(rc=$rc)"
  sed -i "s/^DOCKER_GID=.*/DOCKER_GID=$(stat -c %g "$S/docker.sock")/" "$S/opt/.env"
  sed -i '/^MODULE_MANAGER_TOKEN=/d' "$S/opt/.env"
  out="$(run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"MODULE_MANAGER_TOKEN is missing"* ]]; } || fail="$fail no-token(rc=$rc)"
  printf 'MODULE_MANAGER_TOKEN=%s\n' "$(printf 'a%.0s' $(seq 64))" >>"$S/opt/.env"
  out="$(COBBLE_DOCTOR_FAKE_DOWN=1 run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"http"* ]]; } || fail="$fail fake-down(rc=$rc)"
  chmod 644 "$S/opt/.env"
  out="$(run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"env"* ]]; } || fail="$fail env-mode(rc=$rc)"
  chmod 600 "$S/opt/.env"
  out="$(STUB_UNIT_DOWN=1 run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"systemd"* ]]; } || fail="$fail unit-down(rc=$rc)"
  out="$(STUB_NO_LISTEN=1 run_cli doctor 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"FAIL"*"port"* ]]; } || fail="$fail port(rc=$rc)"
  [ -z "$fail" ] && ok doctor || ko doctor "$fail"
}

t_cli_misc() {
  new_sandbox cli
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || {
    ko cli_misc "install failed"
    return
  }
  local out rc fail=""
  out="$(run_cli backup 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" == *"not available yet"* ]]; } || fail="$fail backup"
  out="$(run_cli restore 2>&1)" && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || fail="$fail restore"
  run_cli nonsense >/dev/null 2>&1 && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || fail="$fail unknown"
  out="$(run_cli help 2>&1)" && [[ "$out" == *"doctor"* && "$out" == *"modules"* ]] || fail="$fail help"
  out="$(run_cli modules list 2>&1)" && grep -q 'exec -T api python -m cobble.cli modules list' "$STUB_LOG" || fail="$fail modules-passthrough"
  out="$(run_cli modules install forgejo --yes 2>&1)" && grep -q 'cobble.cli modules install forgejo --yes' "$STUB_LOG" || fail="$fail modules-args"
  out="$(STUB_MODULES_RC=3 run_cli modules list 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 3 ] && [[ "$out" == *"could not reach the module-manager"* ]]; } || fail="$fail modules-unreachable(rc=$rc)"
  out="$(STUB_MODULES_RC=1 run_cli modules list 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 1 ] && [[ "$out" != *"could not reach"* ]]; } || fail="$fail modules-refusal(rc=$rc)"
  out="$(run_cli version 2>&1)" && [[ "$out" == *"cobble 0."* ]] || fail="$fail version"
  out="$(run_cli reset-admin --yes 2>&1)" && [[ "$out" == *"/activate?token="* ]] && grep -q 'cobble.cli reset-admin' "$STUB_LOG" || fail="$fail reset-admin"
  out="$(run_cli status 2>&1)" && grep -q ' ps$' "$STUB_LOG" || fail="$fail status"
  run_cli reset-admin </dev/null >/dev/null 2>&1 && rc=0 || rc=$?
  [ "$rc" -ne 0 ] || fail="$fail reset-admin-needs-confirm"
  out="$(COBBLE_DIR="$S/nowhere" run_cli status 2>&1)" && rc=0 || rc=$?
  [ "$rc" -eq 1 ] || fail="$fail not-installed"
  out="$(run_cli update 2>&1)" && rc=0 || rc=$?
  { [ "$rc" -eq 0 ] && grep -q 'up -d --build --wait' "$STUB_LOG" && ls "$S"/opt/.env.bak-* >/dev/null 2>&1; } || fail="$fail update"
  [ -z "$fail" ] && ok cli_misc || ko cli_misc "$fail"
}

t_uninstall() {
  new_sandbox uninst
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || {
    ko uninstall "install failed"
    return
  }
  local fail=""
  run_cli uninstall --keep-data --yes >/dev/null 2>&1 || fail="$fail keep-rc"
  { [ -f "$S/opt/.env" ] && [ ! -d "$S/opt/src" ] && [ ! -e "$S/bin/cobble" ] && [ ! -e "$S/unit/cobble.service" ]; } || fail="$fail keep-state"
  grep -q ' down --remove-orphans' "$STUB_LOG" && ! grep -q ' down -v' "$STUB_LOG" || fail="$fail keep-no-volumes"
  # reinstall, then full uninstall
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || fail="$fail reinstall"
  run_cli uninstall --yes >/dev/null 2>&1 || fail="$fail full-rc"
  { [ ! -e "$S/opt" ] && [ ! -e "$S/bin/cobble" ]; } || fail="$fail full-state"
  grep -q ' down -v --remove-orphans' "$STUB_LOG" || fail="$fail full-volumes"
  [ -z "$fail" ] && ok uninstall || ko uninstall "$fail"
}

t_source_tarball() {
  new_sandbox tarball
  tar -C "$S/src" -czf "$S/cobble.tar.gz" --transform 's,^\.,cobble,' .
  local out
  out="$(bash "$INSTALLER/install.sh" --yes --dir "$S/opt" --gpu none --source "$S/cobble.tar.gz" 2>&1)" &&
    [ -f "$S/opt/src/core/compose.yml" ] && ok source_tarball || ko source_tarball "$out"
}

t_source_bad() {
  new_sandbox badsrc
  mkdir -p "$S/empty"
  local rc
  bash "$INSTALLER/install.sh" --yes --dir "$S/opt" --source "$S/empty" >/dev/null 2>&1 && rc=0 || rc=$?
  [ "$rc" -eq 1 ] && ok source_bad || ko source_bad "rc=$rc"
}

for t in $(declare -F | awk '{print $3}' | grep '^t_'); do
  if [ -z "$FILTER" ] || [[ "$t" == *"$FILTER"* ]]; then "$t"; fi
done

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
