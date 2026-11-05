# Releasing (maintainers)

Design: `docs/decisions/0023-release-pipeline.md`. A tag `vX.Y.Z` publishes the core images on GHCR
and a GitHub release with four assets: `cobble.tar.gz`, `cobble.tar.gz.sha256`, `install.sh`,
`install.sh.sha256`. The tarball contains `core/compose.release.yml`, which pins every image CI built.

## Steps

1. **Module images first.** Run the *Module images* workflow (`images.yml`, Actions tab, "Run
   workflow") on the commit to release. Copy the `PIN-THESE` list from its summary, then:
   ```bash
   python3 scripts/pin_images.py ghcr.io/<owner>/cobble-agent-service@sha256:<digest> ...
   git diff catalog/   # only the digests change
   ```
   Commit (`chore: pin module images for vX.Y.Z`) and merge. Module images are pinned in the
   manifests BEFORE tagging; the release workflow does not rebuild them.
2. **Changelog.** Move the `Unreleased` entries of `CHANGELOG.md` under `## [X.Y.Z] - date` and add
   the notes `docs/releases/vX.Y.md` if the version has one (it becomes the release text; otherwise
   GitHub generates it). Make sure `make lint test` passes on `main`.
3. **Dry run (optional, recommended for the first release).** Actions, *Release*, "Run workflow",
   tag `v0.0.0-dryrun`. It builds all images without pushing and attaches the assets (with
   placeholder digests) to the run. Nothing is published.
4. **Tag** the merged commit and push the tag:
   ```bash
   git switch main && git pull
   git tag -s vX.Y.Z -m "Cobble X.Y.Z" && git push origin vX.Y.Z
   ```
   A tag with a suffix (`v0.3.0-rc.1`) creates a pre-release.
5. **Check the assets** once the *Release* run is green:
   ```bash
   gh release view vX.Y.Z --json assets --jq '.assets[].name'   # the 4 files
   mkdir /tmp/rel && cd /tmp/rel
   gh release download vX.Y.Z && sha256sum -c cobble.tar.gz.sha256 install.sh.sha256
   tar -tzf cobble.tar.gz | head                                  # one top-level cobble-X.Y.Z/
   tar -xzOf cobble.tar.gz cobble-X.Y.Z/core/compose.release.yml  # 5 images, with @sha256:
   ```
   **First release only: make the packages public.** On GitHub, the repository's *Packages*: each
   `cobble-*` package (api, worker, module-manager, ui, fake-llm), Package settings, Change
   visibility, Public. Check with `docker logout ghcr.io && docker pull ghcr.io/<owner>/cobble-ui:X.Y.Z`.
6. **Test the one-liner** on a clean VM (see `docs/en/install.md`):
   ```bash
   curl -fsSL https://github.com/<owner>/Cobble/releases/latest/download/install.sh | sudo bash
   ```
   It must pull images (no build), start the stack and show the activation link.

## If it fails
- A job fails before the release step: nothing is published as a release; fix, delete the tag
  (`git push origin :refs/tags/vX.Y.Z`, `git tag -d vX.Y.Z`) and tag again. Images already pushed under
  that version tag are harmless (the override pins digests, not tags).
- Never edit a published release's assets by hand: cut a new patch version.
