# ADR 0023 — Release pipeline: published images, self-contained release

Status: **proposed** (written with `.github/workflows/release.yml`, which has not run yet).

## Context
The installer used to download the source and build the core images on the user's machine (slow,
needs build tools and network access to npm and PyPI, and the result is not the image CI tested). A
release must instead be self-contained: images built once by CI, pinned by digest, and a source
tarball that tells compose to use them.

## Decision
- **Trigger**: pushing a `v*` tag runs `.github/workflows/release.yml`. `workflow_dispatch` with a tag
  name is a dry run: it builds every image without pushing, uses placeholder digests, builds the assets
  and keeps them as a workflow artifact. It never creates a release. Only `GITHUB_TOKEN` is used
  (`packages: write` in the image job, `contents: write` in the release job).
- **Images** (`ghcr.io/<owner lower-cased>/cobble-<service>:<version>@sha256:<digest>`): every service
  of `core/compose.yml` that has `build:` is published, whatever its profile:
  `api`, `worker`, `module-manager`, `ui` and `fake-llm`. `api` and `worker` share one Dockerfile
  target, so it is built once and pushed under both names (same digest). `module-manager` is a
  different target, with the Docker CLI. `fake-llm` is included because the default stack needs it:
  `litellm` waits for it, and it answers until a real model connection is added. `module-manager`
  (profile `modules`) is included because the installer starts it to install modules.
  Third-party images (postgres, redis, litellm, caddy) are already pinned by digest in `compose.yml`.
- **Labels**: `org.opencontainers.image.source` (this is what links a GHCR package to the repository),
  `revision`, `version`, `licenses`, `vendor`. Builds are not bit-for-bit reproducible (apt, timestamps);
  what is reproducible is the input: base images by digest, locked dependencies (`uv.lock`,
  `pnpm-lock.yaml`), and the digest actually published is what gets pinned. No provenance attestation,
  so the digest is a plain image manifest, like `images.yml`.
- **`core/compose.release.yml`** is generated, never committed, by `scripts/make_release_compose.py`
  from `core/compose.yml` and the digests: for each built service
  `image: ghcr.io/<owner>/cobble-<service>:<version>@sha256:<digest>`, `build: !reset null` and
  `pull_policy: always` (`!reset` needs Compose 2.24+, which the Docker the installer installs
  provides; checked with Compose 5.6: the merged config has no `build:` left). Output is sorted and deterministic; it fails when a built service has no
  digest or a digest is given for a service that does not build. The release job also checks that
  `docker compose config --images` shows no local build left and that each digest exists in the registry.
- **Assets** of the GitHub release for `vX.Y.Z`: `cobble.tar.gz`, `cobble.tar.gz.sha256`, `install.sh`,
  `install.sh.sha256` (one `sha256sum` line each: `<hex>  <file>`). The tarball is `git archive` of the
  tagged commit under one top-level `cobble-X.Y.Z/` (so `tar --strip-components=1` works), plus
  `core/compose.release.yml`. Because only tracked files are in it, there is no `.git`, `node_modules`,
  `.venv`, cache, `ui/dist` or `reference-projects/results`. Order, owner and mtime are fixed.
  `scripts/make_release_bundle.sh` builds them and is unit-tested.
- **Module images are not built here.** `images.yml` (agent-service, agent-proxy, preview-service, Aider
  runner) already runs on `v*` tags and by hand, and `scripts/pin_images.py` writes their digests into the
  catalogue manifests. That must be done and merged BEFORE tagging, so the tagged tree already carries
  them. Duplicating it would pin digests built after the tagged commit.

## Consequences
- GHCR packages created by a workflow are private at first. After the first release the maintainer
  makes each `cobble-*` package public once (the installer pulls without credentials).
- A tag whose images fail to build creates no release; fix, delete the tag, tag again.
- The installer must use `core/compose.yml` + `core/compose.release.yml` from the extracted tarball.
- Not verified until the workflow has run once: the action versions' behaviour and the visibility step.
