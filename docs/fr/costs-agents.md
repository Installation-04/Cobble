# API des agents et des coûts

Toutes les routes sont sous `/api/v1`, exigent le cookie de session, ne voient que les projets
de l'appelant (sinon `404`), et les `POST` exigent l'en-tête `X-Requested-With: cobble`.

## Suivre et piloter une tâche

| Route | Réponse |
|---|---|
| `GET /projects/{id}/tasks/{ref}/logs?offset=N` | `200 text/plain`, le journal du dernier run à partir de `offset`; l'en-tête `X-Next-Offset` donne le prochain offset à demander. Retombe sur la fin de journal stockée si le service d'agents n'a plus le run. À interroger toutes les 2 s tant que la tâche tourne. |
| `GET /projects/{id}/tasks/{ref}/diff` | `200 {"diff": "...", "truncated": false}`: diff unifié de la branche de la tâche contre `main` (coupé à 200 Ko, `truncated` vaut alors vrai). Vide avant le premier push. `503 git_unavailable` si le serveur git est injoignable. |
| `POST .../pause` `.../resume` `.../stop` `.../retry` | `200` avec la tâche (même forme que la liste). `409 wrong_state` (params `{state}`) si l'action n'est pas permise; `503 agent_unavailable` quand un run doit être arrêté et que le service d'agents est injoignable (rien n'a changé, réessayer). |

Chaque changement publie `task.updated` sur le flux du projet. Toutes les actions sont idempotentes.

| État de la tâche | pause | resume | stop | retry |
|---|---|---|---|---|
| `todo` | `paused` | sans effet | `stopped` | sans effet |
| `writing_tests`, `implementing`, `ci` | `paused` | sans effet | `stopped` | 409 |
| `paused` (retenue par vous) | sans effet | reprend | `stopped` | `todo` (409 tant qu'un run est actif) |
| `paused` (attend un créneau ou le budget) | retenue | sans effet | `stopped` | `todo` |
| `stopped` | 409 | 409 | sans effet | `todo` |
| `failed`, `blocked` | 409 | 409 | 409 | `todo` |
| `merged` | 409 | 409 | 409 | 409 |

- Le planificateur laisse une tâche en pause tranquille; un run déjà lancé continue mais n'est
  suivi de nouveau qu'après `resume` (qui remet la tâche en `writing_tests`, `implementing` ou
  `ci`, ou laisse le planificateur lancer le run suivant).
- `stop` termine le run actif; la tâche n'est jamais relancée avant `retry`.
- `retry` remet à zéro les tentatives, l'escalade et la dernière erreur, garde la branche,
  marque les runs précédents `retired` (ils restent visibles mais ne comptent plus comme
  tentatives) et libère les tâches bloquées uniquement à cause de celle-ci.

## Coûts

`GET /projects/{id}/costs`:

```json
{
  "budget_usd": "5.00", "spent_usd": "0.17651235",
  "tokens": {"prompt": 1711, "completion": 708},
  "estimate_usd": "1.50",
  "by_task":  [{"ref": "T-002", "cost_usd": "0.0215", "prompt_tokens": 440, "completion_tokens": 100, "calls": 3},
               {"ref": null, "cost_usd": "0.15", "prompt_tokens": 1200, "completion_tokens": 600, "calls": 3}],
  "by_model": [{"model": "strong", "cost_usd": "0.17", "prompt_tokens": 1500, "completion_tokens": 630, "calls": 3}],
  "by_role":  [{"role": "planner", "cost_usd": "0.15", "prompt_tokens": 1200, "completion_tokens": 600, "calls": 2}]
}
```

Les montants sont des chaînes avec 2 à 8 décimales. `ref: null` regroupe les appels sans tâche
(planification). `by_task` est trié par numéro de tâche (null en dernier); `by_model` et
`by_role` par coût décroissant. `estimate_usd` est l'estimation du plan approuvé (`null` s'il
n'y en a pas). `budget_usd` vaut `null` si le budget est illimité.

`GET /costs` liste les projets de l'appelant: `[{"project_id", "name", "spent_usd", "budget_usd", "status"}]`.

`GET /models/prices` (tout utilisateur connecté) : `{"prices": [{"model", "prompt_per_million_usd",
"completion_per_million_usd", "free", "changed", "previous_prompt_per_million_usd",
"previous_completion_per_million_usd", "changed_at"}], "change_window_days": 14}`, les modèles dont le
prix a changé en premier. Il lit les prix de la passerelle et garde le dernier vu: un changement de
prix d'un fournisseur apparaît comme `changed` pendant 14 jours (ADR 0013). Rien n'est réordonné:
c'est un avertissement.

Le rapport de coûts a aussi `free_calls` (appels à des modèles de palier gratuit, comptés comme
gratuits: coût nul), `by_model[].free` et `price_changes` (changements récents parmi les modèles
utilisés par le projet). **Paliers gratuits** : un modèle à prix nul pour la passerelle, ou un modèle
`:free` d'OpenRouter. Les modèles locaux ne sont pas des paliers gratuits. Mise en garde: les paliers
gratuits ont leurs propres limites de débit et conditions (entraînement sur vos requêtes, offre
modifiable); Cobble ne peut pas les vérifier pour vous, et un projet « local seulement » les évite
complètement. Sur un 429, le modèle suivant de la route répond et le modèle limité est essayé en
dernier pendant 30 s (en doublant jusqu'à 10 min).

### Électricité et plafonds par tâche (ADR 0021)

`GET`/`PUT /api/v1/settings/costs` (admin ; aussi Réglages → Modèles et `cobble costs`) :
`electricity_price_kwh_usd`, `electricity_watts`, `electricity_counts_in_budget` et
`task_budget_multiplier`. Avec un prix et une puissance, chaque appel à un modèle servi sur cette
machine enregistre `electricity_usd = watts x secondes de réponse / 3,6e6 x prix`. **C'est une
estimation, pas une mesure.** Le rapport de coûts a `api_usd` (ce que les fournisseurs ont facturé) et
`electricity` (`usd`, `seconds`, `calls`, `counts_in_budget`) sur une ligne à part ; `spent_usd`
n'inclut l'électricité que si `electricity_counts_in_budget` est actif (le budget du projet et le
compteur d'économies l'incluent alors aussi). Chaque ligne `by_task` a `cap_usd` : une tâche peut
dépenser son multiple (3 par défaut) de son estimation, au moins 0,05 USD ; 0 désactive le plafond.
Au-delà, les appels de la tâche sont refusés (HTTP 402 `task_budget_reached`) et le projet continue.
Un appel déjà en cours quand un plafond est franchi se termine : un projet ou une tâche peut dépasser
d'un appel.

## Rapport de fin de projet

`GET /projects/{id}/report` (onglet « Rapport » du projet) résume le projet. Il marche aussi
avant la fin: `project.finished` vaut alors faux et les chiffres sont ceux du moment.

```json
{
  "project": {"id": "…", "name": "Todo", "phase": "done", "status": "active", "finished": true},
  "span": {"started_at": "…", "ended_at": "…", "duration_seconds": 11100},
  "build": {
    "milestones": [{"ref": "M1", "title": "…", "status": "validated", "validated_at": "…",
                    "tasks_total": 4, "tasks_done": 3, "tasks_failed": 1}],
    "milestones_validated": 1,
    "tasks": {"total": 4, "done": 3, "failed": 1, "escalated": 2, "attempts": 6}
  },
  "costs": {
    "spent_usd": "0.17", "budget_usd": "5.00", "estimate_usd": "1.50",
    "budget_used_percent": 3, "estimate_delta_percent": -89,
    "tokens": {"prompt": 1711, "completion": 708},
    "savings": {"reference_model": "…", "saved_usd": "…", "saved_percent": 92, "…": "…"},
    "by_model": [], "by_role": [], "fallbacks": {"calls": 0, "total_calls": 0, "by_model": []}
  }
}
```

`span.ended_at` est la dernière activité (dernière tâche modifiée ou dernier jalon validé).
`costs.savings` est le compteur d'économies de l'onglet Coûts (`null` si le modèle le plus fort
n'a pas de prix). `GET /projects/{id}/report?format=md` renvoie le même rapport en Markdown, à
télécharger (`Content-Disposition: attachment`), dans la langue de l'utilisateur (`fr` ou `en`).
Un autre `format` donne `422`. Le rapport coûte un nombre fixe de requêtes SQL.
