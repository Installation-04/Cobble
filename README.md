<h1 align="center">Cobble</h1>

<p align="center">
  <b>Describe an idea. Inexpensive agents build it. CI is the referee. You approve a demo.</b><br>
  <i>Décrivez une idée. Des agents peu coûteux la construisent. La CI arbitre. Vous validez une démo.</i>
</p>

<p align="center">
  <a href="https://github.com/Installation-04/Cobble/actions"><img alt="CI" src="https://github.com/Installation-04/Cobble/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="License AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-blue">
  <img alt="Status" src="https://img.shields.io/badge/status-v0.1%20release%20candidate-orange">
</p>

<p align="center"><img src="docs/images/09-agents-done.png" alt="Cobble — agents tab" width="860"></p>

**English** · [Français](#français)

---

## What is Cobble?

Cobble is a **free, self-hosted platform** that turns an idea into a working application at the lowest possible cost.

1. **You describe your idea in a chat.** A strong model (the *planner*) asks targeted questions, writes a spec and splits it into a plan of small, testable tasks.
2. **You approve the plan and its cost estimate** before any code is written.
3. **Inexpensive agents write the code**, one isolated container per task, *tests first*: one agent writes the tests, another implements until they pass.
4. **CI is the referee**: a task is only "done" when CI is green; otherwise the merge is refused.
5. **You approve a demo at each milestone**: validate it, comment on it (the comment becomes a task) or go back to the previous milestone.

Every model call goes through a model gateway (LiteLLM) and a **cost router** with a per-project budget and a hard cap. Cost is shown everywhere, in dollars and tokens.

> **Status**: v0.1 **release candidate**. The code is complete and CI is green, but **real validation on a clean machine with a real API key has not been done yet**. See [`docs/releases/v0.1.md`](docs/releases/v0.1.md). The screenshots below use the fake model provider and the development "fake pack": the demo shown is fictional.

## The journey in screenshots

| | |
|---|---|
| ![Activation](docs/images/01-activate.png) **1. Activation** — the admin account is created from a one-use link. | ![Home](docs/images/02-home.png) **2. Projects in folders**, EN/FR, light/dark. |
| ![Interview](docs/images/04-interview.png) **3. Interview** — the planner asks questions and answers in your language. | ![Spec](docs/images/05-spec.png) **4. Spec** — approve it or ask for changes. |
| ![Plan](docs/images/06-plan.png) **5. Plan** — tasks with dependencies, files, acceptance criteria and a cost estimate. | ![Approval](docs/images/07-plan-approve.png) **6. Cost announced** before launch. |
| ![Agents](docs/images/09-agents-done.png) **7. Agents** — tasks by state, one container each. | ![Log](docs/images/10-task-log.png) **8. Live log** of every task. |
| ![Diff](docs/images/11-task-diff.png) **9. Diff** of the task. | ![Demo](docs/images/12-demo.png) **10. Demo per milestone** — validate, comment, revert. |
| ![App](docs/images/14-generated-app.png) **11. The generated app**, with realistic data. | ![Costs](docs/images/15-costs.png) **12. Costs** by task, model and role. |
| ![Dark](docs/images/16-agents-dark.png) **Dark mode** through theme tokens. | ![French](docs/images/17-agents-fr.png) **Bilingual UI**, English and French. |

## Quick start

### Try it locally (no API key needed)

```bash
make install
make dev                # starts everything with a fake model provider
make activation-link    # one-use link to create the admin account
```

Open `http://localhost:8080`. See [`docs/en/dev.md`](docs/en/dev.md).

### Install on a server (Ubuntu 24.04/26.04, Debian 12/13)

```bash
curl -fsSL <install.sh URL> | sudo bash
```

The script installs Docker (official repository), the core in `/opt/cobble`, a systemd service and the `cobble` CLI, then prints the activation link. It is idempotent. See [`docs/en/install.md`](docs/en/install.md). CLI: `cobble status | logs | update | doctor | reset-admin | uninstall`.

## How it is built

```
 Browser ──HTTP──▶ Caddy ──▶ UI (React) · API (FastAPI) ──▶ Postgres · Redis
                                       │
              worker ─▶ planner · scheduler ─▶ cost router ─▶ LiteLLM ─▶ models
                                       │
   pack service (only one touching Docker) ─▶ isolated Aider agents · Forgejo · Woodpecker · previews
```

- **Capabilities, not products**: the core talks to `GitProvider`, `CIProvider`, `AgentRunner` and `LLMClient`; Forgejo, Woodpecker and Aider are the *fixed pack* of v0.1.
- **Agent security**: non-root containers, no Docker socket, CPU/RAM/PID/time limits, read-only root filesystem, no network except an allowlist proxy, no Git credentials inside the container; model calls go through the cost router with a signed per-run token.
- **Reproducible**: Docker images pinned by digest, locked dependencies, fully bilingual UI and messages.

## Useful commands

| Command | Purpose |
|---|---|
| `make dev` / `make dev-down` | start / stop the core locally |
| `make lint test` | checks and unit tests (backend, UI, installer) |
| `make test-integration` | tests with real Postgres, Redis and LiteLLM |
| `make e2e` | browser tests (Playwright) of the whole journey, in "fake pack" mode |
| `make screenshots` | regenerate the images in `docs/images/` |
| `make e2e-full` | the full real chain (manual, long) |

## Limits of v0.1

Plain HTTP only (no automatic HTTPS), amd64 only, no GPU/Ollama in the pack (hosted model APIs only), no `backup`/`restore`, a single worker instance. The full real chain (Forgejo + Woodpecker + Aider + previews) was verified in pieces but not yet end to end.

## Documentation

[Wiki and guides (`docs/wiki`)](docs/wiki/Home.md) · [Installation](docs/en/install.md) · [Development](docs/en/dev.md) · [Pack](docs/en/pack.md) · [Agents](docs/en/agents.md) · [Demos](docs/en/demo.md) · [Architecture decisions](docs/decisions/) · [Full plan (French)](PLAN.md) · [Release notes](docs/releases/v0.1.md)

## Contributing, security, license

[CONTRIBUTING.md](CONTRIBUTING.md) (DCO sign-off) · [SECURITY.md](SECURITY.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Core under **AGPL-3.0**; the project template (`templates/`) is **Apache-2.0**: generated applications belong to you.

---

## Français

### Qu'est-ce que Cobble ?

Cobble est une plateforme **libre et auto-hébergée** qui transforme une idée en application fonctionnelle, au coût le plus bas possible: un chat planifie, des agents peu coûteux codent dans des conteneurs isolés (tests d'abord), la CI arbitre, et vous validez une démo à chaque jalon. Tous les appels de modèle passent par un **routeur de coûts** avec un budget par projet et un plafond dur.

> **État**: v0.1, candidate à la version. Le code est complet et la CI est verte, mais **la validation réelle sur une machine vierge avec une vraie clé d'API n'a pas encore été faite** ([`docs/releases/v0.1.md`](docs/releases/v0.1.md)). Les captures utilisent le faux fournisseur de modèles: la démo affichée est factice.

### Démarrer

```bash
make install
make dev                # lance tout avec un faux fournisseur de modèles (aucune clé)
make activation-link    # lien à usage unique pour créer le compte admin
```

Ouvrir `http://localhost:8080` ([`docs/fr/dev.md`](docs/fr/dev.md)). Pour installer sur un serveur (Ubuntu 24.04/26.04, Debian 12/13): `curl -fsSL <URL de install.sh> | sudo bash` ([`docs/fr/install.md`](docs/fr/install.md)).

### Comment c'est construit

Le noyau parle à des **capacités** (`GitProvider`, `CIProvider`, `AgentRunner`, `LLMClient`), jamais à un produit: Forgejo, Woodpecker et Aider sont le pack fixe de la v0.1. Les agents tournent dans des conteneurs verrouillés (non-root, sans socket Docker, limites de ressources, système de fichiers en lecture seule, réseau uniquement via un proxy à liste blanche, aucun identifiant Git dans le conteneur, appels de modèle par jeton signé via le routeur de coûts). Images Docker épinglées par digest, dépendances verrouillées, interface et messages entièrement bilingues.

### Limites de la v0.1

HTTP seulement, amd64 seulement, pas de GPU/Ollama dans le pack, pas de `backup`/`restore`, une seule instance de worker. La chaîne réelle complète n'a été vérifiée que par morceaux.

### Documentation, contribuer, licence

[Wiki (`docs/wiki`)](docs/wiki/Home.md) · [Guides FR](docs/fr/) · [Décisions d'architecture](docs/decisions/) · [Plan complet](PLAN.md) · [Notes de version](docs/releases/v0.1.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md). Noyau sous **AGPL-3.0**; le gabarit de projet (`templates/`) est sous **Apache-2.0**: les applications générées vous appartiennent.
