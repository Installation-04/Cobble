# Catalogue of modules

One directory per module: `catalog/<id>/manifest.yaml` (validated by `cobble_sdk`), its compose
file and its hooks. The module-manager reads this directory; it is mounted read-only, at the same
absolute path as on the host (see `core/compose.yml`).

The official modules arrive with the v0.2 conversion of the v0.1 pack
(`docs/decisions/0008-module-manager.md`); so far: `forgejo` (capability `git`). Do not put
anything here that is not a module. `backend/tests/unit/test_catalog.py` checks every module
(valid manifest, compose accepted by the platform rules, images as declared, hooks present).

How a module is written:
- `manifest.yaml` declares what it provides/requires, its secrets and which of them the core may
  read (`core_secrets`), its web path (served by Caddy) and its hooks.
- `compose.yml` is plain compose with no host port: the platform rewrites names, networks and
  limits. Variables available: `COBBLE_SECRET_<KEY>` (its declared secrets), `COBBLE_PUBLIC_URL`,
  `COBBLE_PUBLIC_HOST`, `COBBLE_MODULE_ID`.
- Hooks are bash, idempotent, and run with a minimal environment (the variables above plus
  `PATH`). A hook gives a secret back with a line `::secret::KEY=VALUE`; nothing else is read.
