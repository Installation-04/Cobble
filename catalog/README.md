# Catalogue of modules

One directory per module: `catalog/<id>/manifest.yaml` (validated by `cobble_sdk`), its compose
file and its hooks. The module-manager reads this directory; it is mounted read-only, at the same
absolute path as on the host (see `core/compose.yml`).

Empty for now: the official modules arrive with the v0.2 conversion of the v0.1 pack
(`docs/decisions/0008-module-manager.md`). Do not put anything here that is not a module.
