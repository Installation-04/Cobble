#!/usr/bin/env bash
# Publish docs/wiki/*.md to the GitHub wiki of the repository.
#
# Prerequisites (once): on GitHub, Settings > Features > enable "Wikis", then create any first
# page in the Wiki tab (GitHub only creates the wiki repository at that moment).
# Usage: scripts/publish_wiki.sh [owner/repo]     (uses your own git credentials)
set -euo pipefail

REPO="${1:-Installation-04/Cobble}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git clone "https://github.com/${REPO}.wiki.git" "$TMP/wiki"
cp "$ROOT"/docs/wiki/*.md "$TMP/wiki/"
cd "$TMP/wiki"
git add -A
if git diff --cached --quiet; then
  echo "Wiki already up to date."
  exit 0
fi
git commit -s -m "docs: update the wiki from docs/wiki"
git push
echo "Wiki published: https://github.com/${REPO}/wiki"
