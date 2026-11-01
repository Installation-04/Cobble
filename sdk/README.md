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
Planned next: the dependency resolver, the compose rewriter, and the `cobble-sdk init|lint|test` CLI.
