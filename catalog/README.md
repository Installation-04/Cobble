# Catalogue of modules

One directory per module: `catalog/<id>/manifest.yaml` (validated by `cobble_sdk`), its compose
file and its hooks. The module-manager reads this directory; it is mounted read-only, at the same
absolute path as on the host (see `core/compose.yml`).

The official modules (`docs/en/modules.md`): `forgejo` (`git`), `woodpecker` (`ci`), `ollama`
(`llm-backend`), `aider` (`agent-runner`) and `preview` (`preview`). Do not put anything here that
is not a module or a starter pack. The images of `aider` and `preview` are built by CI
(`.github/workflows/images.yml`) and pinned here with `scripts/pin_images.py`.

`packs/<id>.yaml` are the **starter packs**: named sets of modules proposed at first launch, with
the hardware they ask for and a priority (the fitting pack with the highest priority is the one
recommended). A pack only lists modules: installing it is installing those modules in one
operation, and it must resolve with nothing left to choose (a test checks it). Today: `local-gpu`,
`local-cpu`, `api-only`. The remote GPU node pack of the plan needs several machines and comes with
multi-node support. `backend/tests/unit/test_catalog.py` checks every module
(valid manifest, compose accepted by the platform rules, images as declared, hooks present).

How a module is written:
- `manifest.yaml` declares what it provides/requires, its secrets and which of them the core may
  read (`core_secrets`), its web path (served by Caddy) and its hooks.
- `compose.yml` is plain compose with no host port: the platform rewrites names, networks and
  limits. Variables available: `COBBLE_SECRET_<KEY>` (its declared secrets), `COBBLE_PUBLIC_URL`,
  `COBBLE_PUBLIC_HOST`, `COBBLE_MODULE_ID`.
- Hooks are bash, idempotent, and run with a minimal environment (the variables above plus
  `PATH`). A hook gives a secret back with a line `::secret::KEY=VALUE`; nothing else is read.
