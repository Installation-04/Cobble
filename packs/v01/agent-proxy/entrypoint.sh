#!/bin/sh
# Build the tinyproxy config from AGENT_PROXY_ALLOW (comma separated host names) and run it.
# Every entry must be a plain host name: letters, digits, dots, dashes. A leading "*." allows
# all sub-domains. Anything else aborts the start (no silent widening of the allow-list).
set -eu
ALLOW="${AGENT_PROXY_ALLOW:-}"
[ -n "$ALLOW" ] || { echo "AGENT_PROXY_ALLOW is empty: refusing to start without an allow-list" >&2; exit 64; }
FILTER=/tmp/allow.txt
: > "$FILTER"
old_ifs="$IFS"; IFS=','
for entry in $ALLOW; do
  host="$(printf '%s' "$entry" | tr -d ' ' | tr 'A-Z' 'a-z')"
  [ -n "$host" ] || continue
  printf '%s' "$host" | grep -Eq '^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$' \
    || { echo "invalid allow-list entry: $host" >&2; exit 64; }
  case "$host" in
    '*.'*) printf '%s\n' "^([a-z0-9-]+\\.)+$(printf '%s' "${host#\*.}" | sed 's/\./\\./g')\$" >> "$FILTER" ;;
    *) printf '%s\n' "^$(printf '%s' "$host" | sed 's/\./\\./g')\$" >> "$FILTER" ;;
  esac
done
IFS="$old_ifs"
[ -s "$FILTER" ] || { echo "allow-list has no valid entry" >&2; exit 64; }
sed "s#@FILTER_FILE@#$FILTER#" /etc/tinyproxy/tinyproxy.conf.tmpl > /tmp/tinyproxy.conf
echo "agent-proxy allow-list:" >&2; sed 's/^/  /' "$FILTER" >&2
exec tinyproxy -d -c /tmp/tinyproxy.conf
