# Development

**English** · [Français](#français)

## Setup

Python 3.12+ (uv), Node 22 (pnpm), Docker with Compose v2, and `make`.

```bash
make install     # locked dependencies (uv, pnpm)
make dev         # the whole core with a fake model provider (no key)
make smoke       # one chat request through LiteLLM + the cost row in the database
make lint test   # ruff, strict mypy, eslint, i18n, colors; unit tests
```

## Tests

| Command | What it covers |
|---|---|
| `make test` | unit tests (backend, fake provider, agent-service, preview service, UI, installer) |
| `make test-integration` | real Postgres, Redis and LiteLLM (migrations up and down, full flows) |
| `make e2e` | browser (Playwright) on a fresh stack, in **fake pack** mode |
| `make e2e-full` | the full real chain (manual, 20 minutes or more) |
| `make screenshots` | regenerate `docs/images/` |

Tests **never call a real model**: they use the fake provider and its **cassettes** (JSON; the key is a hash of the model and messages, or a task marker for agents). Re-record a cassette on purpose with `make cassettes` (secrets are scrubbed automatically).

## Repository rules

- Code, comments and commits in **English**; user documentation in **English and French**.
- No hard-coded visible string (`en` and `fr` i18n files, enforced by `make lint`); colors **only through theme tokens**.
- Every database schema change goes through an **Alembic migration** tested both ways.
- **Conventional Commits**, signed off (**DCO**, `git commit -s`); update `CHANGELOG.md`.

See [CONTRIBUTING.md](https://github.com/Installation-04/Cobble/blob/main/CONTRIBUTING.md).

---

## Français

## Mise en place

Python 3.12+ (uv), Node 22 (pnpm), Docker avec Compose v2, `make`.

```bash
make install     # dépendances verrouillées (uv, pnpm)
make dev         # tout le noyau, faux fournisseur de modèles (aucune clé)
make smoke       # une requête de chat via LiteLLM + la ligne de coût en base
make lint test   # ruff, mypy strict, eslint, i18n, couleurs; tests unitaires
```

## Tests

| Commande | Ce que ça couvre |
|---|---|
| `make test` | unitaires (backend, faux fournisseur, agent-service, aperçu, UI, installateur) |
| `make test-integration` | Postgres, Redis et LiteLLM réels (migrations montée/descente, flux complets) |
| `make e2e` | navigateur (Playwright) sur une pile neuve, en **faux pack** |
| `make e2e-full` | chaîne réelle complète (manuel, 20 min et plus) |
| `make screenshots` | régénère `docs/images/` |

Les tests **n'appellent jamais un vrai modèle**: ils utilisent le faux fournisseur et ses **cassettes** (JSON, clé = hachage du modèle et des messages, ou marqueur de tâche pour les agents). Une cassette se réenregistre volontairement avec `make cassettes` (les secrets sont retirés automatiquement).

## Règles du dépôt

- Code, commentaires et commits en **anglais**; documentation utilisateur en **français et anglais**.
- Aucune chaîne visible en dur (fichiers i18n `fr` et `en`, vérifiés par `make lint`); couleurs **uniquement par jetons de thème**.
- Toute évolution du schéma de base passe par une **migration Alembic** testée dans les deux sens.
- Commits **Conventional Commits**, signés **DCO** (`git commit -s`); mettre à jour `CHANGELOG.md`.

Voir [CONTRIBUTING.md](https://github.com/Installation-04/Cobble/blob/main/CONTRIBUTING.md).
