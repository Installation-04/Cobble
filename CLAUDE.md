# CLAUDE.md — Cobble

Cobble est une plateforme libre et auto-hébergée qui transforme une idée en application: un chat planifie, des agents peu coûteux codent dans des conteneurs isolés, la CI arbitre, l'utilisateur valide une démo. Le plan complet est dans `PLAN.md`; **le lire avant toute tâche importante**.

## Version en cours

**v0.2 — Magasin et modules.** Voir `PLAN.md` section 14 et `docs/decisions/0008-module-manager.md`. Le propriétaire a demandé de commencer v0.2 avant la validation de l'étape 11 de v0.1 (dérogation explicite à `PLAN.md` §18; le code de v0.1 est livré, sa validation sur VM vierge avec un vrai modèle reste à faire et `v0.1.0` n'est pas publiée). Ne rien implémenter qui appartient à une version ultérieure (v0.3 et suivantes), même si c'est tentant. Les idées hors portée vont dans une issue avec l'étiquette `idée`.

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
sdk/                   # SDK des modules: schéma de manifeste, validation (licence Apache-2.0, n'importe jamais `cobble`)
installer/             # install.sh, CLI cobble
reference-projects/    # projets de référence du banc d'essai (specs + tests cachés)
docs/fr/  docs/en/
```

## Commandes

```
make install      # uv sync + pnpm install (versions verrouillées)
make format       # ruff + prettier (écriture)
make dev          # lance le noyau en local avec le faux fournisseur LLM (aucune clé requise)
make dev-down     # arrête le noyau; make dev-logs suit les journaux
make activation-link  # lien à usage unique pour créer le compte admin
make smoke        # une requête de chat via LiteLLM + la ligne de coût enregistrée
make dev-modules  # le noyau + le module-manager (profil compose `modules`)
make smoke-modules  # installe le module Forgejo via le vrai module-manager, vérifie, désinstalle
cobble modules list|status|install|uninstall   # (installé) gère les modules via le module-manager
make test-integration  # Postgres/Redis/LiteLLM réels (pile + core/compose.test.yml)
make cassettes    # réenregistre des cassettes contre un vrai fournisseur (coûte des tokens)
make test         # tests unitaires backend + frontend
make lint         # ruff, mypy, eslint, vérification des clés i18n
make e2e          # Playwright sur l'UI, pile neuve (efface les volumes de dev); boucle complète avec cassettes à venir
make e2e-full       # chaîne réelle complète (Forgejo, Woodpecker, Aider...), manuel, long
make bench        # banc d'essai des agents (vrais modèles, coûte des tokens: ne pas lancer en CI)
```

Les cibles `lint-backend`, `lint-ui`, `test-backend` et `test-ui` existent aussi (utilisées par la CI). `make bench` échoue avec un message tant que leur étape n'est pas livrée.

`COMPOSE_FLAGS="-f autre.yml"` ajoute des fichiers compose (voir `docs/fr/dev.md`).

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
- Licences: le dépôt est AGPL-3.0; `templates/` et `sdk/` sont Apache-2.0 avec leur propre fichier `LICENSE`. Toute nouvelle dépendance doit avoir une licence compatible; le signaler dans la PR.
- Pas de nouvelle dépendance lourde sans justification dans la PR.

## Définition de « terminé »

Une tâche est terminée quand: le code et les tests sont écrits, `make lint test` passe, les chaînes sont traduites, la doc FR/EN est à jour si le comportement visible change, et le critère d'acceptation de l'étape est démontré (commande ou test à l'appui).

## En cas de doute

Relire `PLAN.md`. Si le plan ne tranche pas, choisir l'option la plus simple qui respecte les règles ci-dessus, la noter dans `docs/decisions/` (court ADR), et continuer.
