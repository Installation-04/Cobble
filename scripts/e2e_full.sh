#!/usr/bin/env bash
# Full-chain end-to-end run of the to-do reference project (manual harness, `make e2e-full`).
#
# Brings up core + pack (Forgejo, Woodpecker) + agents + previews with freshly generated secrets,
# activates the admin through the API, creates a project, replays the scripted interview, spec
# and plan (cassettes of the fake LLM), approves the plan, starts the build and follows it until
# the project phase is `done`: tasks tests-first with the fake-LLM agent cassettes
# (providers/fake-llm/cassettes/agent-todo-*.json), CI, merge, one demo per milestone
# (validated here through the API). Prints the final task table, tokens, cost and elapsed time,
# then tears everything down.
#
# Usage: scripts/e2e_full.sh [--keep] [--timeout SECONDS] [--lang en|fr] [--comment] [--force]
#   --keep      leave the stack running (and print how to remove it)
#   --timeout   give up after this many seconds of building (default 3600)
#   --comment   after `done`, comment on the last demo and follow the new C-001 task
#   --force     start even though packs/v01 already holds generated secrets (they are DELETED
#               at teardown unless --keep)
# Environment: E2E_PORT (host port of Caddy, default 18080), E2E_EMAIL, E2E_PASSWORD,
# E2E_HOST (address CI containers use to reach the stack, default: first address of this host),
# E2E_BUILD_CA (path of a CA bundle passed to every image build as the optional `ca` BuildKit
# secret; for hosts behind a TLS-inspecting proxy, unset by default).
#
# Uses only the documented APIs (ADR 0003, 0005, 0006, 0007). Endpoints that answer 404 are
# reported as SKIPPED instead of failing the run (the harness predates some of them).
# Needs: docker compose (v2), curl, python3 (standard library only). Needs network access to
# pull images and the registries the agents use. It uses the fixed compose project names of
# the core (`cobble`) and the pack, so it refuses to run next to a dev stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEEP=0
TIMEOUT=3600
LANG_CODE=en
COMMENT=0
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --keep) KEEP=1 ;;
    --timeout) TIMEOUT="${2:?--timeout needs a value}"; shift ;;
    --lang) LANG_CODE="${2:?--lang needs en or fr}"; shift ;;
    --comment) COMMENT=1 ;;
    --force) FORCE=1 ;;
    -h | --help) sed -n 2,22p "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
case "$LANG_CODE" in en | fr) ;; *) echo "--lang must be en or fr" >&2; exit 2 ;; esac

PORT="${E2E_PORT:-18080}"
# CI step containers clone from the public URL, so it must be reachable from a container: a
# non-loopback address of this host (E2E_HOST overrides), not `localhost`.
HOST="${E2E_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
BASE="http://${HOST:-localhost}:$PORT"
EMAIL="${E2E_EMAIL:-admin@example.com}"
PASSWORD="${E2E_PASSWORD:-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')}"
WORK="$(mktemp -d)"
CORE_ENV="$WORK/core.env"
JAR="$WORK/cookies"
PACK="$ROOT/packs/v01"
STARTED=$(date +%s)
FAILED=0

log() { printf '[e2e-full %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
skip() { printf '[e2e-full] SKIPPED: %s\n' "$*"; }
die() { printf '[e2e-full] ERROR: %s\n' "$*" >&2; exit 1; }

# Optional build-time CA (see E2E_BUILD_CA): one override file per compose project.
CA_CORE=() CA_AGENTS=() CA_PREVIEW=() CA_PACK=""
if [ -n "${E2E_BUILD_CA:-}" ]; then
  [ -r "$E2E_BUILD_CA" ] || die "E2E_BUILD_CA is not readable: $E2E_BUILD_CA"
  export BUILDX_BAKE_ENTITLEMENTS_FS=0
  ca_override() { # ca_override FILE SERVICE...
    local file="$1"; shift
    { echo "services:"
      for svc in "$@"; do printf '  %s:\n    build:\n      secrets: [ca]\n' "$svc"; done
      printf 'secrets:\n  ca:\n    file: %s\n' "$E2E_BUILD_CA"; } >"$file"
  }
fi

core() { docker compose -p cobble --env-file "$CORE_ENV" -f "$ROOT/core/compose.yml" "${CA_CORE[@]}" "$@"; }

# --- preflight ---------------------------------------------------------------------------------
for tool in docker curl python3; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is required"
done
docker compose version >/dev/null 2>&1 || die "docker compose v2 is required"
if [ -n "$(docker compose -p cobble ps -q 2>/dev/null)" ]; then
  die "a stack named 'cobble' is running (make dev?): stop it first, this run wipes its volumes"
fi
if [ "$FORCE" -ne 1 ] && { [ -e "$PACK/.env" ] || [ -e "$PACK/.env.pack" ]; }; then
  die "$PACK already holds generated secrets (a pack is installed): use --force to replace them"
fi

# --- teardown ----------------------------------------------------------------------------------
teardown() {
  local rc=$?
  trap - EXIT
  if [ "$KEEP" -eq 1 ]; then
    log "stack kept. Open $BASE (admin $EMAIL). Remove it with:"
    log "  docker compose -p cobble --env-file $CORE_ENV -f core/compose.yml down -v"
    log "  packs/v01/hooks/uninstall.sh --purge   # and the agents/preview projects"
    exit "$rc"
  fi
  log "tearing down"
  docker compose -p cobble-pack-preview -f "$PACK/compose.preview.yml" down -v >/dev/null 2>&1 || true
  docker compose -p cobble-pack-agents -f "$PACK/compose.agents.yml" down -v >/dev/null 2>&1 || true
  "$PACK/hooks/uninstall.sh" --purge >/dev/null 2>&1 || true
  core down -v >/dev/null 2>&1 || true
  rm -f "$PACK/.env.agents" "$PACK/.env.agents.core" "$PACK/.env.preview" "$PACK/.env.preview.core" \
    "$PACK/caddy/demo.caddy"
  rm -rf "$WORK"
  exit "$rc"
}
trap teardown EXIT

# --- small helpers -----------------------------------------------------------------------------
# api METHOD PATH [JSON]  -> prints the HTTP status; the body is left in $WORK/body
api() {
  local method="$1" path="$2" data="${3:-}"
  local args=(-sS -o "$WORK/body" -w '%{http_code}' -X "$method" -b "$JAR" -c "$JAR"
    -H 'X-Requested-With: cobble' "$BASE/api/v1$path")
  if [ -n "$data" ]; then args+=(-H 'Content-Type: application/json' --data "$data"); fi
  curl "${args[@]}" || echo 000
}

# jq-less JSON access: jget EXPRESSION (over the last body, bound to `d`). The expressions are
# literals of this script, never built from server data, so eval is safe here.
jget() {
  python3 -c 'import json,sys
d = json.load(open(sys.argv[1]))
print(eval(sys.argv[2]))' "$WORK/body" "$1"
}

jstr() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

# wait_for DESCRIPTION SECONDS COMMAND...  (command succeeds when the wait is over)
wait_for() {
  local what="$1" limit="$2" i=0
  shift 2
  while ! "$@"; do
    i=$((i + 2))
    [ "$i" -lt "$limit" ] || die "timeout waiting for: $what"
    sleep 2
  done
}

# --- 1. secrets and stack ------------------------------------------------------------------------
log "generating secrets in $WORK"
python3 "$ROOT/scripts/dev_env.py" "$CORE_ENV" >/dev/null
sed -i "s/^COBBLE_HTTP_PORT=.*/COBBLE_HTTP_PORT=$PORT/;s/^COBBLE_LANG=.*/COBBLE_LANG=$LANG_CODE/" "$CORE_ENV"
{
  echo "COBBLE_PUBLIC_URL=$BASE"
  echo "COBBLE_ENV=development"
} >>"$CORE_ENV"

if [ -n "${E2E_BUILD_CA:-}" ]; then
  ca_override "$WORK/ca-core.yml" fake-llm api worker ui
  ca_override "$WORK/ca-agents.yml" agent-proxy agent-service agent-runner-image
  ca_override "$WORK/ca-preview.yml" preview-service
  CA_CORE=(-f "$WORK/ca-core.yml") CA_AGENTS=(-f "$WORK/ca-agents.yml") CA_PREVIEW=(-f "$WORK/ca-preview.yml")
fi

log "starting the core (project cobble)"
core up --build -d --wait

log "installing the pack (Forgejo, Woodpecker)"
COBBLE_PACK_PUBLIC_URL="$BASE" "$PACK/hooks/install.sh"

log "building and starting agent-service, the egress proxy and the runner image"
docker compose -f "$PACK/compose.agents.yml" "${CA_AGENTS[@]}" --profile build build
"$PACK/agent-service/gen-env.sh"
docker compose -f "$PACK/compose.agents.yml" up -d

log "building and starting preview-service"
docker compose -f "$PACK/compose.preview.yml" "${CA_PREVIEW[@]}" build
"$PACK/preview-service/gen-env.sh"
docker compose -f "$PACK/compose.preview.yml" up -d
cp "$PACK/preview-service/demo.caddy" "$PACK/caddy/demo.caddy"

log "restarting api, worker and caddy to load the pack settings"
core up -d --force-recreate --wait api worker caddy

# --- 2. admin account ------------------------------------------------------------------------------
log "activating the admin account"
link="$(core exec -T api python -m cobble.cli activation-link | grep -Eo 'https?://[^ ]+' | head -n 1)"
token="${link##*token=}"
[ -n "$token" ] || die "no activation token in the activation link"
status="$(api POST /auth/activate "{\"token\":\"$token\",\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"lang\":\"$LANG_CODE\"}")"
[ "$status" = 201 ] || die "activation answered $status: $(cat "$WORK/body")"

# --- 3. project, interview, spec, plan ---------------------------------------------------------------
status="$(api POST /projects '{"name":"Todo list"}')"
[ "$status" = 201 ] || die "project creation answered $status"
PID="$(jget 'd["id"]')"
log "project $PID"

# The scripted user messages live in the cassette generator (parsed, not imported).
mapfile -t MESSAGES < <(python3 - "$ROOT/providers/fake-llm/scripts/make_todo_cassettes.py" "$LANG_CODE" <<'PY'
import ast, sys
tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "USER_MESSAGES":
        for message in ast.literal_eval(node.value)[sys.argv[2]]:
            print(message)
PY
)
[ "${#MESSAGES[@]}" -ge 2 ] || die "could not read USER_MESSAGES from make_todo_cassettes.py"

message_count() { api GET "/projects/$PID/messages" >/dev/null; jget 'len(d)'; }
reply_arrived() { [ "$(message_count)" -ge "$1" ] && [ "$(jget 'd[-1]["role"]')" = assistant ]; }

expected=0
for text in "${MESSAGES[@]}"; do
  status="$(api POST "/projects/$PID/messages" "{\"content\":$(jstr "$text")}")"
  [ "$status" = 202 ] || die "message answered $status: $(cat "$WORK/body")"
  expected=$((expected + 2))
  wait_for "the planner's reply ($expected messages)" 120 reply_arrived "$expected"
done
log "interview done"

have() { [ "$(api GET "$1")" = 200 ]; } # a resource exists
log "generating the spec"
[ "$(api POST "/projects/$PID/spec/generate" '{}')" = 202 ] || die "spec/generate refused"
wait_for "the spec" 120 have "/projects/$PID/spec"
[ "$(api POST "/projects/$PID/spec/approve")" = 200 ] || die "spec/approve refused"

log "generating the plan"
[ "$(api POST "/projects/$PID/plan/generate" '{}')" = 202 ] || die "plan/generate refused"
wait_for "the plan" 120 have "/projects/$PID/plan"
api GET "/projects/$PID/plan" >/dev/null
log "plan: $(jget 'len(d["plan"]["tasks"])') tasks, estimate $(jget 'd["estimate"].get("tokens")') tokens, \$$(jget 'd["estimate"].get("cost_usd")')"
[ "$(api POST "/projects/$PID/plan/approve")" = 200 ] || die "plan/approve refused"

# --- 4. build -----------------------------------------------------------------------------------------
log "starting the build"
BUILD_STARTED=$(date +%s)
[ "$(api POST "/projects/$PID/start")" = 202 ] || die "start refused"

phase() { api GET /projects >/dev/null; jget "[p['phase'] for p in d if p['id'] == '$PID'][0]"; }

MILESTONES_SEEN=1
validate_built_milestones() {
  local status refs ref
  status="$(api GET "/projects/$PID/milestones")"
  if [ "$status" = 404 ]; then
    if [ "$MILESTONES_SEEN" = 1 ]; then skip "milestones endpoint missing (demo flow not validated)"; fi
    MILESTONES_SEEN=0
    return 0
  fi
  [ "$status" = 200 ] || return 0
  refs="$(jget '" ".join(m["ref"] for m in d if m["status"] == "built")')"
  for ref in $refs; do
    log "validating the demo of milestone $ref"
    api POST "/projects/$PID/milestones/$ref/validate" >/dev/null
  done
}

task_states() { # prints "state=count ..." for the last GET /tasks
  jget '" ".join(f"{k}={v}" for k, v in sorted(__import__("collections").Counter(t["state"] for t in d).items()))'
}

follow() { # follow UNTIL_PHASE_DONE
  local deadline=$((BUILD_STARTED + TIMEOUT)) last="" now current states
  while :; do
    now=$(date +%s)
    [ "$now" -lt "$deadline" ] || { log "TIMEOUT after ${TIMEOUT}s"; FAILED=1; return 1; }
    current="$(phase)"
    if [ "$(api GET "/projects/$PID/tasks")" = 200 ]; then
      states="$(task_states)"
      if [ "$states" != "$last" ]; then log "phase=$current $states"; last="$states"; fi
      if jget 'any(t["state"] in ("failed", "blocked") for t in d)' | grep -q True; then
        log "a task failed or is blocked"; FAILED=1; return 1
      fi
    fi
    validate_built_milestones
    [ "$current" = "done" ] && return 0
    sleep 5
  done
}

follow || true
if [ "$FAILED" -eq 0 ] && [ "$COMMENT" -eq 1 ]; then
  status="$(api GET "/projects/$PID/milestones")"
  if [ "$status" = 200 ]; then
    last_ref="$(jget 'd[-1]["ref"]')"
    log "commenting on milestone $last_ref"
    comment='{"content":"Add a due date to every task and show it in the list."}'
    status="$(api POST "/projects/$PID/milestones/$last_ref/comments" "$comment")"
    if [ "$status" = 201 ]; then
      BUILD_STARTED=$(date +%s)
      follow || true
    else
      skip "comments endpoint answered $status"
    fi
  else
    skip "milestones endpoint answered $status (comment flow not run)"
  fi
fi

# --- 5. report ------------------------------------------------------------------------------------------
echo
log "final tasks"
if [ "$(api GET "/projects/$PID/tasks")" = 200 ]; then
  python3 - "$WORK/body" <<'PY'
import json, sys
tasks = json.load(open(sys.argv[1]))
print(f"{'task':<9}{'milestone':<10}{'state':<14}{'attempts':<9}escalated  depends_on")
for t in tasks:
    print(f"{t['ref']:<9}{t['milestone']:<10}{t['state']:<14}{t['attempts']:<9}{str(t['escalated']):<11}{','.join(t['depends_on'])}")
PY
fi

status="$(api GET "/projects/$PID/costs")"
if [ "$status" = 200 ]; then
  log "costs: spent \$$(jget 'd["spent_usd"]'), prompt tokens $(jget 'd["tokens"]["prompt"]'), completion tokens $(jget 'd["tokens"]["completion"]')"
else
  skip "costs endpoint answered $status: reading the llm_calls table instead"
  core exec -T postgres psql -U cobble -d cobble -At -F ' ' -c \
    "SELECT 'calls=' || count(*), 'prompt_tokens=' || coalesce(sum(prompt_tokens), 0), 'completion_tokens=' || coalesce(sum(completion_tokens), 0), 'cost_usd=' || coalesce(sum(cost_usd), 0) FROM llm_calls" || true
fi

elapsed=$(($(date +%s) - STARTED))
log "elapsed ${elapsed}s ($((elapsed / 60)) min), final phase: $(phase)"
if [ "$FAILED" -eq 0 ] && [ "$(phase)" = "done" ]; then
  log "RESULT: PASS"
else
  log "RESULT: FAIL"
  core logs --tail=60 worker || true
  exit 1
fi
