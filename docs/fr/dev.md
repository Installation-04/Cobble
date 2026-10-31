# Pile de développement

```bash
make dev          # génère core/.env (secrets aléatoires), construit et démarre tout
make smoke        # une requête de chat via LiteLLM vers le faux fournisseur + la ligne enregistrée
make dev-logs     # suivre les journaux
make dev-down     # arrêter (les volumes de données sont conservés)
```

Aucune clé d'API n'est nécessaire: LiteLLM envoie le modèle `fake` au faux fournisseur, qui rejoue les cassettes de `providers/fake-llm/cassettes/`.

Ouvrir `http://localhost:8080` (santé: `/api/v1/health`). Seul Caddy publie un port; le changer avec `COBBLE_HTTP_PORT` dans `core/.env`.

## Première connexion

`make dev` affiche l'URL. Créer le compte admin avec le lien d'activation à usage unique (valable 24 heures, consommé à l'usage):

```bash
make activation-link
```

Ouvrir le lien affiché, choisir un courriel et un mot de passe (10 caractères ou plus), puis se connecter. `make e2e` lance le test navigateur (Playwright) sur une pile **neuve**: il efface d'abord les volumes de données de développement.

| Service | Rôle |
|---|---|
| `caddy` | Seul port publié; route `/api/*` vers l'API, le reste vers l'UI |
| `api` | FastAPI; applique les migrations Alembic au démarrage |
| `worker` | Consomme le flux d'événements Redis |
| `litellm` | Passerelle de modèles (version épinglée) |
| `fake-llm` | Fournisseur compatible OpenAI qui rejoue des cassettes |
| `postgres`, `redis` | État et bus d'événements |
| `ui` | Application React (build Vite) servie par Caddy, non-root |

## Tests

- `make test`: tests unitaires (aucun service requis).
- `make test-integration`: démarre la pile avec `core/compose.test.yml` (ports sur 127.0.0.1 seulement) et lance les tests d'intégration: migrations montée et descente sur un vrai Postgres, vrai contrôle de santé, et la chaîne complète chat → LiteLLM → cassette → base de données.

## Derrière un proxy qui inspecte le TLS

Les constructions d'images échouent avec des erreurs de certificat sur ces réseaux. Fournir votre bundle CA comme secret de build optionnel `ca` via un fichier compose supplémentaire:

```yaml
# my-ca.yml
services:
  api: { build: { secrets: [ca] } }
  worker: { build: { secrets: [ca] } }
  fake-llm: { build: { secrets: [ca] } }
secrets:
  ca: { file: /chemin/vers/ca-bundle.crt }
```

```bash
make dev COMPOSE_FLAGS="-f my-ca.yml"
```

Si BuildKit demande des privilèges sur le système de fichiers, définir `BUILDX_BAKE_ENTITLEMENTS_FS=0`.
