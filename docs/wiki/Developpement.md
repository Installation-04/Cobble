# Développement / Development

**Français** · [English](#english)

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

---

## English

Needs Python 3.12+ (uv), Node 22 (pnpm), Docker with Compose v2 and `make`. `make install`, `make dev` (no API key), `make smoke`, `make lint test`. Tests: `make test` (unit), `make test-integration` (real Postgres/Redis/LiteLLM), `make e2e` (Playwright in fake pack mode), `make e2e-full` (manual full real chain), `make screenshots`. Tests **never call a real model**: they use the fake provider and its cassettes; re-record on purpose with `make cassettes` (secrets are scrubbed). Rules: English code/commits, FR+EN user docs, no hard-coded UI strings, colors only via theme tokens, every schema change through a tested Alembic migration, Conventional Commits with DCO sign-off, update `CHANGELOG.md`.
