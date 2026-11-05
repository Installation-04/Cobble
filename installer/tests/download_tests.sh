# --- download from GitHub: URL resolution, SHA-256 verification (offline: local HTTP server) ---

SERVER_PID=""
stop_server() {
  [ -z "$SERVER_PID" ] || kill "$SERVER_PID" 2>/dev/null
  SERVER_PID=""
}

# start_server DIR: serve DIR on a free local port; sets PORT.
start_server() {
  local log="$TMP/server.log" i
  : >"$log"
  python3 -u -m http.server 0 --bind 127.0.0.1 --directory "$1" >"$log" 2>&1 &
  SERVER_PID=$!
  PORT=""
  for i in $(seq 1 50); do
    PORT="$(sed -n 's/.* port \([0-9][0-9]*\).*/\1/p' "$log" | head -n 1)"
    [ -z "$PORT" ] || return 0
    sleep 0.1
  done
  return 1
}

# fake_release PATH MARKER: PATH.tar.gz holds a tree whose installer/install.sh prints MARKER and
# its arguments (what the bootstrap hands over), and PATH.tar.gz.sha256 is a valid checksum line.
fake_release() {
  local dest="$1" marker="$2" w
  w="$(mktemp -d "$TMP/rel.XXXXXX")"
  mkdir -p "$w/cobble-top/installer" "$(dirname "$dest")"
  printf '#!/usr/bin/env bash\necho "RAN:%s:$*"\n' "$marker" >"$w/cobble-top/installer/install.sh"
  tar -C "$w" -czf "$dest.tar.gz" cobble-top
  (cd "$(dirname "$dest")" && sha256sum "$(basename "$dest").tar.gz" >"$(basename "$dest").tar.gz.sha256")
}

# run_remote ARGS...: the install.sh script alone (as with curl | bash) against the local server.
run_remote() {
  PATH="$ORIG_PATH" COBBLE_GITHUB_URL="http://127.0.0.1:$PORT" COBBLE_CODELOAD_URL="http://127.0.0.1:$PORT/codeload" \
    bash "$S/solo/install.sh" "$@" 2>&1
}

new_remote_sandbox() {
  new_sandbox "$1"
  local www="$S/www" repo=Installation-04/Cobble
  mkdir -p "$S/solo"
  cp "$INSTALLER/install.sh" "$S/solo/install.sh"
  fake_release "$www/$repo/releases/latest/download/cobble" latest
  fake_release "$www/$repo/releases/download/v1.2.3/cobble" v123
  fake_release "$www/Fork/Repo/releases/latest/download/cobble" fork
  fake_release "$www/codeload/$repo/tar.gz/main.tmp" ref
  mv "$www/codeload/$repo/tar.gz/main.tmp.tar.gz" "$www/codeload/$repo/tar.gz/main"
  rm -f "$www/codeload/$repo/tar.gz/main.tmp.tar.gz.sha256"
  # a release whose checksum does not match, and one without any checksum
  fake_release "$www/$repo/releases/download/v9.9.9/cobble" bad
  printf '%064d  cobble.tar.gz\n' 0 >"$www/$repo/releases/download/v9.9.9/cobble.tar.gz.sha256"
  fake_release "$www/$repo/releases/download/v8.8.8/cobble" nosum
  rm "$www/$repo/releases/download/v8.8.8/cobble.tar.gz.sha256"
  start_server "$www"
}

t_remote_url_resolution() {
  new_remote_sandbox remote_urls
  local out fail=""
  out="$(run_remote --yes)" && [[ "$out" == "RAN:latest:--yes --source "* ]] || fail="$fail latest($out)"
  out="$(run_remote --version v1.2.3 --yes)" && [[ "$out" == "RAN:v123:--yes --source "* && "$out" != *"--version"* ]] || fail="$fail version($out)"
  out="$(run_remote --version=1.2.3)" && [[ "$out" == "RAN:v123:"* ]] || fail="$fail version-no-v($out)"
  out="$(COBBLE_REPO=Fork/Repo run_remote)" && [[ "$out" == "RAN:fork:"* ]] || fail="$fail repo($out)"
  out="$(run_remote --source "http://127.0.0.1:$PORT/Installation-04/Cobble/releases/download/v1.2.3/cobble.tar.gz")" && [[ "$out" == "RAN:v123:"* ]] || fail="$fail source-url($out)"
  out="$(run_remote --ref main)" && [[ "$out" == *"RAN:ref:"* && "$out" == *"NOT a verified release"* && "$out" == *"PAS une version vérifiée"* ]] || fail="$fail ref($out)"
  out="$(run_remote --version v1.2.3 --ref main)" && fail="$fail conflict-accepted" || [[ "$out" == *"only one of"* && "$out" == *"un seul"* ]] || fail="$fail conflict-msg($out)"
  out="$(run_remote --version banana)" && fail="$fail bad-version-accepted" || [[ "$out" == *"Invalid --version"* ]] || fail="$fail bad-version-msg($out)"
  out="$(run_remote --ref 'a;b')" && fail="$fail bad-ref-accepted" || [[ "$out" == *"Invalid --ref"* ]] || fail="$fail bad-ref-msg($out)"
  out="$(COBBLE_REPO='x y' run_remote)" && fail="$fail bad-repo-accepted" || [[ "$out" == *"Invalid COBBLE_REPO"* ]] || fail="$fail bad-repo-msg($out)"
  stop_server
  [ -z "$fail" ] && ok remote_url_resolution || ko remote_url_resolution "$fail"
}

t_remote_checksum() {
  new_remote_sandbox remote_sum
  local out fail="" base="http://127.0.0.1:$PORT/Installation-04/Cobble/releases/download"
  out="$(run_remote --version v1.2.3)" && [[ "$out" == "RAN:v123:"* ]] || fail="$fail ok($out)"
  out="$(run_remote --version v9.9.9)" && fail="$fail mismatch-accepted" || {
    [[ "$out" == *"SHA-256 mismatch"* && "$out" == *"SHA-256 différent"* && "$out" != *"RAN:"* ]] || fail="$fail mismatch-msg($out)"
  }
  out="$(run_remote --version v8.8.8)" && fail="$fail missing-accepted" || {
    [[ "$out" == *"Checksum file not found"* && "$out" == *"somme de contrôle introuvable"* && "$out" != *"RAN:"* ]] || fail="$fail missing-msg($out)"
  }
  out="$(run_remote --source "$base/v8.8.8/cobble.tar.gz" --no-verify)" && [[ "$out" == *"RAN:nosum:"* && "$out" == *"NOT checked"* && "$out" == *"--no-verify"* ]] || fail="$fail no-verify($out)"
  out="$(run_remote --version v9.9.9 --no-verify)" && [[ "$out" == *"RAN:bad:"* ]] || fail="$fail no-verify-mismatch($out)"
  stop_server
  [ -z "$fail" ] && ok remote_checksum || ko remote_checksum "$fail"
}

t_remote_not_found() {
  new_remote_sandbox remote_404
  local out fail=""
  out="$(COBBLE_REPO=Nobody/None run_remote)" && fail="$fail latest-404-accepted" || {
    [[ "$out" == *"No Cobble release is published yet"* && "$out" == *"Aucune version de Cobble"* && "$out" == *"--ref main"* ]] || fail="$fail latest-404-msg($out)"
  }
  out="$(run_remote --version v7.7.7)" && fail="$fail version-404-accepted" || {
    [[ "$out" == *"Not found (404)"* && "$out" == *"Introuvable (404)"* ]] || fail="$fail version-404-msg($out)"
  }
  stop_server
  [ -z "$fail" ] && ok remote_not_found || ko remote_not_found "$fail"
}

# Installing from a release: compose.release.yml is added to every compose call and nothing is built.
t_release_override() {
  new_sandbox release_override
  local fail="" out
  : >"$S/src/core/compose.release.yml"
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || fail="$fail install"
  [ -f "$S/opt/src/core/compose.release.yml" ] || fail="$fail not-copied"
  grep -q 'core/compose.yml -f .*core/compose.release.yml -f .*compose.install.yml up -d --wait' "$STUB_LOG" || fail="$fail start-flags($(grep ' up ' "$STUB_LOG" | head -n 1))"
  grep -q -- '--build' "$STUB_LOG" && fail="$fail built-anyway"
  grep -q 'compose.release.yml' "$S/unit/cobble.service" || fail="$fail unit"
  : >"$STUB_LOG"
  out="$(run_cli update 2>&1)" || fail="$fail update($out)"
  grep -q 'compose.release.yml .*up -d --wait' "$STUB_LOG" && ! grep -q -- '--build' "$STUB_LOG" || fail="$fail update-flags"
  : >"$STUB_LOG"
  run_cli status >/dev/null 2>&1
  grep -q 'compose.release.yml' "$STUB_LOG" || fail="$fail cli-status"
  # without the file (a checkout, --ref): built from source as before
  new_sandbox no_release_override
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || fail="$fail install2"
  grep -q 'up -d --build --wait' "$STUB_LOG" && ! grep -q 'compose.release.yml' "$STUB_LOG" && ! grep -q 'compose.release.yml' "$S/unit/cobble.service" || fail="$fail checkout-flags"
  [ -z "$fail" ] && ok release_override || ko release_override "$fail"
}

# `cobble update --version/--ref/--latest/--no-verify` are handed to the installer.
t_update_options() {
  new_sandbox update_opts
  local fail="" out
  install_sh --dir "$S/opt" --gpu none >/dev/null 2>&1 || fail="$fail install"
  out="$(run_cli update --version v1.2.3 --no-verify 2>&1)" && fail="$fail offline-accepted"
  [[ "$out" == *"releases/download/v1.2.3/cobble.tar.gz"* && "$out" == *"--no-verify"* ]] || fail="$fail not-forwarded($out)"
  out="$(run_cli update --bogus 2>&1)" && fail="$fail bogus-accepted"
  [[ "$out" == *"Unknown or incomplete option"* ]] || fail="$fail bogus-msg($out)"
  [ -z "$fail" ] && ok update_options || ko update_options "$fail"
}

