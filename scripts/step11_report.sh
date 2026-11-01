#!/usr/bin/env bash
# Read-only report for the step 11 validation (docs/releases/v0.1.md): prints the measurable rows
# of the results table from a running install. It only reads the database; it changes nothing.
#
# Usage: scripts/step11_report.sh [PROJECT_NAME]      (default: the most recent project)
# Environment: COBBLE_DIR (install directory, default /opt/cobble), COBBLE_COMPOSE_PROJECT.
set -euo pipefail

DIR="${COBBLE_DIR:-/opt/cobble}"
NAME="${1:-}"
[ -f "$DIR/.env" ] && [ -f "$DIR/src/core/compose.yml" ] || {
  echo "no Cobble install found in $DIR (set COBBLE_DIR)" >&2
  exit 1
}

compose=(docker compose)
if [ -n "${COBBLE_COMPOSE_PROJECT:-}" ]; then compose+=(-p "$COBBLE_COMPOSE_PROJECT"); fi
compose+=(--env-file "$DIR/.env" -f "$DIR/src/core/compose.yml")
if [ -f "$DIR/compose.install.yml" ]; then compose+=(-f "$DIR/compose.install.yml"); fi

q() { "${compose[@]}" exec -T postgres psql -U cobble -d cobble -At -F '|' -c "$1"; }

# The project: by name when given (the name is checked, never interpolated as SQL).
case "$NAME" in *[!A-Za-z0-9\ _.-]*) echo "unsupported characters in the project name" >&2; exit 2 ;; esac
if [ -n "$NAME" ]; then where="name = '$NAME'"; else where="true"; fi
pid="$(q "SELECT id FROM projects WHERE $where ORDER BY created_at DESC LIMIT 1")"
[ -n "$pid" ] || { echo "no project found" >&2; exit 1; }

echo "| Measure | Value |"
echo "|---|---|"
echo "| Date, version (commit), machine | $(date -u +%F) / $(git -C "$DIR/src" rev-parse --short HEAD 2>/dev/null || echo unknown) / $(uname -sm) |"
echo "| Models per role | $(q "SELECT coalesce(string_agg(role || '=' || model, ', ' ORDER BY role), 'none') FROM (SELECT DISTINCT role, model FROM llm_calls WHERE project_id = '$pid') m") |"
echo "| Total duration of the build | $(q "SELECT coalesce(to_char(max(finished_at) - min(started_at), 'HH24:MI:SS'), 'n/a') FROM task_runs WHERE task_id IN (SELECT id FROM tasks WHERE project_id = '$pid')") |"
echo "| Real cost (USD) and tokens | $(q "SELECT '\$' || coalesce(round(sum(cost_usd), 4), 0) || ', ' || coalesce(sum(prompt_tokens), 0) || ' prompt / ' || coalesce(sum(completion_tokens), 0) || ' completion' FROM llm_calls WHERE project_id = '$pid'") |"
echo "| Number of escalations | $(q "SELECT count(*) FROM tasks WHERE project_id = '$pid' AND escalated") |"
echo "| Failed / blocked tasks | $(q "SELECT count(*) FILTER (WHERE state = 'failed') || ' failed / ' || count(*) FILTER (WHERE state = 'blocked') || ' blocked' FROM tasks WHERE project_id = '$pid'") |"
echo "| Tasks by state | $(q "SELECT coalesce(string_agg(state || '=' || n, ', ' ORDER BY state), 'none') FROM (SELECT state, count(*) n FROM tasks WHERE project_id = '$pid' GROUP BY state) s") |"
echo
echo "Not measurable here (fill in by hand): the estimate shown before launch, green CI on every"
echo "merge (check the pipelines in the CI UI), whether the demo works with data, and the problems"
echo "you ran into."
