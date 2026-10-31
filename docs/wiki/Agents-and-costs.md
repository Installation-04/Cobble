# Agents and costs

**English** · [Français](#français)

## Model roles

| Role | What it does | Model |
|---|---|---|
| `planner` | interview, spec, plan | a strong model |
| `test-writer` | writes a task's tests from its criteria | inexpensive |
| `worker` | implements until the tests pass | inexpensive |
| `reviewer` | review (planned, not active in v0.1) | strong |

Set each role's model with `COBBLE_ROLE_MODELS` (JSON); roles you do not list use the default model. **Escalation**: after a few failures of the same agent, the task moves up to the stronger model (`COBBLE_ESCALATION_MODEL`, by default the planner's).

## The budget

Every project has a **budget** in dollars (\$5.00 by default; editable or unlimited). At 80 % a `budget.warning` event is published; at 100 % the project is **paused** (`budget.reached`) and no further model call is accepted. Raising the budget above the spend **resumes** the project. Calls already in flight when the cap is hit may overshoot it slightly.

## Where every call goes

All model calls, including those of the coding agents, go through the **cost router**. Agents never call LiteLLM directly: they use an internal endpoint with a **signed per-run token** (project, task, role, expiry), so the budget applies and the cost is attributed to the right task.

## Task control

In the **Agents** tab: **pause** (no new run; a running run continues), **resume**, **stop** (stops the current run) and **retry** (resets the attempts). Invalid transitions return a clear error.

## Guardrails

Maximum iterations and duration per run; **loop detection** (the same output line repeated, or the same test failure twice in a row) stops the agent instead of burning tokens; limited attempts per task.

---

## Français

## Les rôles de modèles

| Rôle | Fait quoi | Modèle |
|---|---|---|
| `planner` | entrevue, spec, plan | un modèle fort |
| `test-writer` | écrit les tests d'une tâche à partir des critères | peu coûteux |
| `worker` | implémente jusqu'à ce que les tests passent | peu coûteux |
| `reviewer` | relecture (rôle prévu, pas encore actif en v0.1) | fort |

Le modèle de chaque rôle se règle par `COBBLE_ROLE_MODELS` (JSON); sans réglage, le modèle par défaut est utilisé. **Escalade**: après quelques échecs d'un même agent, la tâche monte au modèle supérieur (`COBBLE_ESCALATION_MODEL`, par défaut celui du planner).

## Le budget

Chaque projet a un **budget** en dollars (5,00 $ par défaut, modifiable ou illimité). À 80 % un avertissement est publié (`budget.warning`); à 100 % le projet est **mis en pause** (`budget.reached`) et plus aucun appel de modèle n'est accepté. Remonter le budget au-dessus de la dépense **relance** le projet. Les appels déjà en cours au moment du plafond peuvent le dépasser légèrement.

## Où va chaque appel

Tous les appels de modèle — y compris ceux des agents de code — passent par le **routeur de coûts**. Les agents n'appellent jamais LiteLLM directement: ils utilisent un point d'accès interne avec un **jeton signé par exécution** (projet, tâche, rôle, expiration), donc le budget s'applique et le coût est attribué à la bonne tâche.

## Contrôle des tâches

Dans l'onglet **Agents**: **pause** (aucune nouvelle exécution; une exécution en cours continue), **reprise**, **arrêt** (stoppe l'exécution en cours), **relance** (remet les tentatives à zéro). Les transitions invalides renvoient une erreur claire.

## Garde-fous

Itérations maximales et durée maximale par exécution; **détection de boucle** (même ligne de sortie répétée, ou même échec de test deux fois de suite) qui arrête l'agent au lieu de brûler des jetons; tentatives limitées par tâche.
