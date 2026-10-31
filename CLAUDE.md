# CLAUDE.md — Cobble

Cobble est une plateforme libre et auto-hébergée qui transforme une idée en application: un chat planifie, des agents peu coûteux codent dans des conteneurs isolés, la CI arbitre, l'utilisateur valide une démo. Le plan complet est dans `PLAN.md`; **le lire avant toute tâche importante**.

## Version en cours

**v0.1 — La boucle fonctionne (pack fixe).** Voir `PLAN.md` section 14. Ne rien implémenter qui appartient à une version ultérieure, même si c'est tentant. Les idées hors portée vont dans une issue avec l'étiquette `idée`.

## Pile

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, Redis (streams) pour la file de tâches et les événements.
- **Frontend**: React + Vite + TypeScript, Tailwind CSS, shadcn/ui (Radix), react-i18next.
- **Passerelle LLM**: LiteLLM (version épinglée). Le backend n'appelle jamais un fournisseur directement.
- **Proxy**: Caddy. **Base**: Postgres.
- **Outils Python**: uv, ruff (lint + format), mypy (strict sur `cobble/`), pytest.
- **Outils web**: pnpm, eslint, prettier, vitest, Playwright.

## Structure du dépôt

```
backend/cobble/        # api/, orchestrator/, scheduler/, router/ (coûts), capabilities/, providers/, db/
backend/migrations/    # Alembic
backend/tests/         # unit/, integration/
ui/                    # React; ui/src/locales/{fr,en}/*.json
core/compose.yml       # noyau: postgres, redis, litellm, caddy, api, worker, ui
packs/v01/             # pack fixe v0.1: forgejo, woodpecker, ollama, hooks de branchement
runners/aider/         # image du runner d'agents
providers/fake-llm/    # faux fournisseur LLM + cassettes enregistrées
templates/fastapi-react/   # gabarit de projet généré (licence Apache-2.0)
installer/             # install.sh, CLI cobble
reference-projects/    # projets de référence du banc d'essai (specs + tests cachés)
docs/fr/  docs/en/
```

## Commandes

```
make dev          # lance le noyau en local avec le faux fournisseur LLM (aucune clé requise)
make test         # tests unitaires backend + frontend
make lint         # ruff, mypy, eslint, vérification des clés i18n
make e2e          # Playwright sur l'UI + boucle complète avec cassettes
make bench        # banc d'essai des agents (vrais modèles, coûte des tokens: ne pas lancer en CI)
```

Tenir cette section à jour quand une commande change.

## Règles non négociables

1. **Capacités, pas produits**: le noyau ne référence jamais Forgejo, Woodpecker, Ollama ou Aider par leur nom. Il passe par les interfaces de `cobble/capabilities/` (`GitProvider`, `CIProvider`, `AgentRunner`, `LLMClient`). Le pack fixe v0.1 implémente ces interfaces.
2. **Tous les appels LLM passent par LiteLLM et par le routeur de coûts**, qui enregistre tokens et coût par tâche. Aucun appel direct à un SDK de fournisseur.
3. **Bilingue**: aucune chaîne visible en dur dans l'UI, la CLI ou les messages d'API destinés à l'utilisateur. Clés ajoutées en `fr` et en `en` dans le même commit; `make lint` échoue sinon.
4. **Mode sombre**: couleurs uniquement via les jetons de thème (variables CSS). Jamais de couleur codée en dur dans un composant.
5. **Sécurité des agents**: les conteneurs d'agents ne reçoivent jamais le socket Docker, ne tournent pas en root, ont des limites CPU/RAM/PID/durée et un réseau restreint. Seul le module-manager (ou, en v0.1, le service de pack) touche à Docker.
6. **Tests**: toute fonctionnalité arrive avec ses tests. Les tests n'appellent jamais un vrai modèle: ils utilisent le faux fournisseur et ses cassettes. Une cassette se réenregistre volontairement avec `make cassettes` (documenté).
7. **Migrations**: tout changement de schéma passe par une migration Alembic testée en montée et en descente.
8. **Secrets**: jamais dans le code, les logs ou les cassettes. Les cassettes sont nettoyées automatiquement avant d'être enregistrées.
9. **Versions épinglées**: images Docker par digest, dépendances verrouillées (`uv.lock`, `pnpm-lock.yaml`).

## Conventions

- Code, identifiants, commentaires et messages de commit en **anglais**; documentation utilisateur en **français et anglais**.
- Commits petits et ciblés, style Conventional Commits (`feat:`, `fix:`, `docs:`…), signés DCO (`git commit -s`).
- Mettre à jour `CHANGELOG.md` (section « Unreleased ») pour tout changement visible.
- Licences: le dépôt est AGPL-3.0; `templates/` et le futur `sdk/` sont Apache-2.0 avec leur propre fichier `LICENSE`. Toute nouvelle dépendance doit avoir une licence compatible; le signaler dans la PR.
- Pas de nouvelle dépendance lourde sans justification dans la PR.

## Définition de « terminé »

Une tâche est terminée quand: le code et les tests sont écrits, `make lint test` passe, les chaînes sont traduites, la doc FR/EN est à jour si le comportement visible change, et le critère d'acceptation de l'étape est démontré (commande ou test à l'appui).

## En cas de doute

Relire `PLAN.md`. Si le plan ne tranche pas, choisir l'option la plus simple qui respecte les règles ci-dessus, la noter dans `docs/decisions/` (court ADR), et continuer.
