#!/usr/bin/env bash
# Build the release assets that are files: cobble.tar.gz, install.sh and their .sha256 files.
#
#   scripts/make_release_bundle.sh <version> <compose.release.yml> <outdir>
#
# The tarball is the tracked source tree at HEAD (so no .git, node_modules, .venv, caches, ui/dist
# or reference-projects/results: none is tracked) under one top-level directory
# `cobble-<version>/`, plus core/compose.release.yml. Order, owner, group and mtime are fixed, so
# the same commit gives the same bytes. The .sha256 files hold one `sha256sum` line.
set -euo pipefail

[ "$#" -eq 3 ] || { echo "usage: $0 <version> <compose.release.yml> <outdir>" >&2; exit 2; }
version="${1#v}"
compose_release="$2"
outdir="$3"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$ ]] || { echo "bad version: $version" >&2; exit 2; }
[ -f "$compose_release" ] || { echo "missing $compose_release" >&2; exit 2; }

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$outdir"
outdir="$(cd "$outdir" && pwd)"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
top="cobble-$version"

git -C "$root" archive --format=tar --prefix="$top/" HEAD | tar -x -C "$stage"
cp "$compose_release" "$stage/$top/core/compose.release.yml"
# Belt and braces: a tracked file must never ship these.
rm -rf "$stage/$top/reference-projects/results" "$stage/$top/ui/dist"
find "$stage/$top" \( -name node_modules -o -name .venv -o -name __pycache__ -o -name .git \) -prune -exec rm -rf {} +

mtime="$(git -C "$root" log -1 --format=%ct HEAD)"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$mtime" -cf - -C "$stage" "$top" \
  | gzip -n -9 > "$outdir/cobble.tar.gz"
cp "$root/installer/install.sh" "$outdir/install.sh"
(cd "$outdir" && sha256sum cobble.tar.gz > cobble.tar.gz.sha256 && sha256sum install.sh > install.sh.sha256)
ls -l "$outdir"
