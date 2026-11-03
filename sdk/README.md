# cobble-sdk

The Cobble module SDK (Apache-2.0, see `LICENSE`). It lets module authors, the module-manager and
the catalogue CI agree on one thing: what a **module manifest** is.

Today (v0.2, work in progress) it provides the manifest schema and its validation:

```python
from cobble_sdk import load_manifest, ManifestError

manifest = load_manifest("catalog/forgejo/manifest.yaml")  # raises ManifestError
```

- Images must be pinned by digest (`name@sha256:<64 hex>`), never `:latest`.
- Unknown fields are errors. Descriptions need both `fr` and `en`.
- The platform's rules (no published host ports, namespaces, networks, limits) are **not** in the
  manifest: the module-manager applies them.
- `schema/manifest.schema.json` is generated: `uv run python -m cobble_sdk.schema` (CI runs `--check`).

This package must never import anything from the AGPL `cobble` package (a test enforces it).
## Writing a module: `cobble-sdk`

```bash
uv run cobble-sdk init my-module --dir catalog   # a skeleton: manifest.yaml + compose.yml
uv run cobble-sdk lint catalog/my-module         # manifest, files, hooks, platform compose rules
uv run cobble-sdk test catalog/my-module         # install and remove it on sample machines
```

- `lint` checks the manifest, that the compose files and hooks exist (hooks executable), that no
  placeholder digest is left, and the platform rules on the compose file as Docker resolves it
  (`docker compose config`; without Docker it says the rules were not checked, or use `--no-compose`).
  Give it a catalogue directory to check every module in it.
- `test` resolves the module against its sibling modules (or `--catalog DIR`) on five sample machines
  (1/4/16 GB, NVIDIA, AMD): it must install, or declare that it does not fit, and removing it must
  leave nothing behind.
- Exit codes: 0 fine, 1 problems found, 2 usage.
