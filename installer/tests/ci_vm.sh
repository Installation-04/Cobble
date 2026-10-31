#!/usr/bin/env bash
# End-to-end install test in a throwaway "VM": a privileged systemd container running
# the given base image, with Docker installed by install.sh inside it (nested Docker).
# Needs a Docker host that allows privileged containers (GitHub-hosted runners do).
# Usage: installer/tests/ci_vm.sh <base-image, e.g. debian:12> [repo-dir]
#
# Storage driver choice: /var/lib/docker of the nested daemon is a named volume (ext4/xfs
# of the host), so the default overlay2 driver works natively and fast. Without that
# volume overlay2 cannot sit on the container's own overlay filesystem and Docker would
# fall back to the slow vfs driver. No fuse-overlayfs is needed.
set -euo pipefail

IMAGE="${1:?usage: ci_vm.sh <base-image> [repo-dir]}"
REPO="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
NAME="cobble-vm-$$"
TAG="cobble-vm:${IMAGE//[:\/]/-}"

in_vm() { docker exec "$NAME" "$@"; }
fail() {
  echo "CI-FAIL: $*" >&2
  exit 1
}

cleanup() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "--- diagnostics (exit $rc) ---" >&2
    in_vm cobble doctor >&2 2>&1 || true
    in_vm tail -n 60 /var/log/cobble-install.log >&2 2>&1 || true
    in_vm journalctl -u docker -u cobble --no-pager -n 40 >&2 2>&1 || true
  fi
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$NAME-docker" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker build -t "$TAG" - <<EOF
FROM $IMAGE
ENV container=docker DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      systemd systemd-sysv dbus ca-certificates curl iproute2 procps \
    && rm -rf /var/lib/apt/lists/*
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
EOF

docker run -d --name "$NAME" --privileged --cgroupns=host \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw -v "$NAME-docker:/var/lib/docker" \
  --tmpfs /run --tmpfs /run/lock --tmpfs /tmp "$TAG" >/dev/null

for _ in $(seq 1 60); do
  state="$(in_vm systemctl is-system-running 2>/dev/null || true)"
  case "$state" in running | degraded) break ;; esac
  sleep 1
done
case "$state" in running | degraded) ;; *) fail "systemd did not start (state: ${state:-none})" ;; esac

docker cp "$REPO/." "$NAME:/src"

echo "=== first install ==="
in_vm env COBBLE_LANG=en bash /src/installer/install.sh --yes --skip-checks --source /src | tee /tmp/cobble-ci-install1.log
link="$(grep -o 'http[^ ]*/activate?token=[A-Za-z0-9_-]*' /tmp/cobble-ci-install1.log | head -n 1)"
[ -n "$link" ] || fail "no activation link printed"
token="${link##*token=}"

in_vm curl -fsS http://localhost/api/v1/health | grep -q '"status":"ok"' || fail "health is not ok"
in_vm systemctl is-active --quiet cobble.service || fail "cobble.service is not active"
[ "$(in_vm stat -c %a /opt/cobble/.env)" = 600 ] || fail ".env is not mode 0600"

# Create the admin so that the re-run has something it must not destroy.
in_vm curl -fsS -X POST http://localhost/api/v1/auth/activate -H 'content-type: application/json' \
  -d "{\"token\":\"$token\",\"email\":\"ci@example.com\",\"password\":\"correct horse battery staple\"}" >/dev/null ||
  fail "admin activation failed"
env_before="$(in_vm sha256sum /opt/cobble/.env)"

echo "=== second install (idempotence) ==="
in_vm env COBBLE_LANG=en bash /src/installer/install.sh --yes --skip-checks --source /src | tee /tmp/cobble-ci-install2.log
[ "$(in_vm sha256sum /opt/cobble/.env)" = "$env_before" ] || fail ".env changed on re-run"
in_vm curl -fsS http://localhost/api/v1/setup/status | grep -q '"initialized":true' || fail "admin lost on re-run"
grep -q 'cobble reset-admin' /tmp/cobble-ci-install2.log || fail "re-run did not report the existing admin"

echo "=== doctor ==="
in_vm cobble doctor || fail "doctor reports a problem on a healthy install"
in_vm docker stop cobble-worker-1 >/dev/null
if in_vm cobble doctor; then fail "doctor did not detect a stopped worker"; fi
in_vm docker start cobble-worker-1 >/dev/null
for _ in $(seq 1 30); do
  if in_vm cobble doctor >/dev/null 2>&1; then break; fi
  sleep 2
done
in_vm cobble doctor || fail "doctor does not recover after the worker restarts"

echo "=== uninstall ==="
in_vm cobble uninstall --yes
in_vm test ! -e /opt/cobble || fail "uninstall left /opt/cobble"
echo "CI-OK: $IMAGE"
