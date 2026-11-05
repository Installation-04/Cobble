# ADR 0022 — Install from GitHub releases with a verified checksum

Status: **proposed** (implemented, waiting for the owner to accept it).

## Context
`install.sh` pointed to a placeholder tarball URL. The documented one-liner
(`curl ... | sudo bash`) needs a real address, and a script run as root that downloads code must
not trust the network blindly. The release workflow (written separately) publishes, for each tag
`vX.Y.Z`: `cobble.tar.gz` (source tree with a top-level directory), `cobble.tar.gz.sha256`,
`install.sh`, `install.sh.sha256`, and the tarball may contain `core/compose.release.yml`.

## Decision
- **Default source: the latest release** (`github.com/<repo>/releases/latest/download/cobble.tar.gz`).
  The one-liner uses `raw.githubusercontent.com/.../main/installer/install.sh`; as a lone script it
  fetches the release tarball and continues with the `install.sh` it contains, so the version that
  runs is the release's own.
- `--version vX.Y.Z` selects one release. `--ref <branch|tag|sha>` uses the GitHub archive
  (`codeload.github.com`) and builds from source; it has no checksum, so a bilingual warning says it
  is not a verified release. `COBBLE_REPO=owner/name` points to a fork. `--source` keeps working.
- **Verification is mandatory** for every URL tarball: download to a temp file, fetch `<url>.sha256`,
  compare SHA-256, unpack only after a match. A mismatch, a missing or malformed checksum stops the
  install. `--no-verify` exists for tests and air-gapped mirrors, documented as unsafe. Curl is never
  piped into tar. A 404 on `releases/latest` says that no release exists and suggests `--ref main`.
- The bootstrap runs before the message catalogs exist, so its messages are bilingual in one block.
- **Published images**: if `core/compose.release.yml` is in the installed tree, `set_compose`, the
  installer's start and the systemd unit add it, and `--build` is dropped. Updating is
  `cobble update --latest|--version|--ref|--source`, which replaces the tree through the same
  fetch-and-verify path, then pulls the pinned images. The override must reset the `build:` key of
  each service (`build: !reset null`), otherwise Compose merges `image` with the old `build`.

## Consequences
- A checksum fetched from the same origin protects against corrupt or swapped assets, not against a
  compromised release; signing (cosign or minisign) is a possible later step.
- Tests serve fixtures from a local HTTP server (`installer/tests/download_tests.sh`), no real network.
