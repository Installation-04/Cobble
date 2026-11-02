# Architecture

**English** · [Français](#français)

## Overview

```
 Browser ──HTTP──▶ Caddy ──▶ UI (React) · API (FastAPI) ──▶ Postgres · Redis
                                       │
              worker ─▶ planner · scheduler ─▶ cost router ─▶ LiteLLM ─▶ models
                                       │
   module-manager (holds the Docker socket) ─▶ modules: Forgejo · Woodpecker · Ollama · isolated Aider agents · previews
```

- **Caddy** is the only service that publishes a port; everything else sits on internal networks.
- **API** (FastAPI, `/api/v1`, OpenAPI): authentication, projects, chat, spec, plan, tasks, milestones, costs. Errors are **codes** that the UI translates.
- **Worker**: runs the long jobs (planner reply, spec and plan generation) and the **scheduler**.
- **Redis**: job queue and event streams (server-sent events to the browser). **Postgres**: all state.
- **LiteLLM** is the only door to models. The **cost router** maps roles (`planner`, `test-writer`, `worker`, `reviewer`) to models, enforces the budget and records tokens and cost per task.

## Capabilities, not products

The core never names Forgejo, Woodpecker, Ollama or Aider: it uses `GitProvider`, `CIProvider`, `AgentRunner`, `LLMClient` and `PreviewProvider`. The **official modules** implement them: Forgejo (Git), Woodpecker (CI with Semgrep, Trivy, Gitleaks), Ollama (local models), Aider (agents) and a preview service, installed from the Store or `cobble modules`. An automated test forbids product names in the core.

## A project's lifecycle

Phases: `interview → spec_review → plan_review → ready → building → done`. The plan is checked by a **strict schema** (no task without acceptance criteria, size S or M only, no dependency cycles).

**Scheduler**: a task starts when its dependencies are merged and its files do not overlap a running task. For each task a *test-writer* agent writes the tests, then a *worker* agent implements; CI runs; the merge is refused unless CI is green. Guardrails: maximum iterations and duration, loop detection, **escalation** to a stronger model after N failures, then `failed` (dependents become `blocked`). All state lives in the database, so a restarted worker **resumes** without redoing anything.

## Architecture decisions

Short, dated records in [`docs/decisions/`](https://github.com/Installation-04/Cobble/tree/main/docs/decisions) (0001 to 0007).

---

## Français

## Vue d'ensemble

```
 Navigateur ──HTTP──▶ Caddy ──▶ UI (React) · API (FastAPI) ──▶ Postgres · Redis
                                          │
                  worker ─▶ planner · ordonnanceur ─▶ routeur de coûts ─▶ LiteLLM ─▶ modèles
                                          │
        gestionnaire de modules (tient le socket Docker) ─▶ modules : Forgejo · Woodpecker · Ollama · agents Aider isolés · aperçus
```

- **Caddy** est le seul service qui publie un port; tout le reste est sur des réseaux internes.
- **API** (FastAPI, `/api/v1`, OpenAPI): authentification, projets, chat, spec, plan, tâches, jalons, coûts. Les erreurs sont des **codes** traduits par l'interface.
- **Worker**: exécute les tâches longues (réponse du planner, génération de la spec et du plan) et l'**ordonnanceur**.
- **Redis**: file de tâches et flux d'événements (SSE vers le navigateur). **Postgres**: tout l'état.
- **LiteLLM**: seule porte vers les modèles. Le **routeur de coûts** mappe les rôles (`planner`, `test-writer`, `worker`, `reviewer`) à des modèles, applique le budget et enregistre jetons et coût par tâche.

## Capacités, pas produits

Le noyau ne nomme jamais Forgejo, Woodpecker, Ollama ni Aider: il utilise `GitProvider`, `CIProvider`, `AgentRunner`, `LLMClient`, `PreviewProvider`. Les **modules officiels** les implémentent: Forgejo (Git), Woodpecker (CI avec Semgrep, Trivy, Gitleaks), Ollama (modèles locaux), Aider (agents), un service d'aperçu, installés depuis le Magasin ou `cobble modules`. Un test automatique interdit les noms de produits dans le noyau.

## Le cycle d'un projet

Phases: `interview → spec_review → plan_review → ready → building → done`. Le plan est validé par un **schéma strict** (aucune tâche sans critère d'acceptation, taille S ou M seulement, dépendances sans cycle).

**Ordonnanceur**: une tâche est lancée quand ses dépendances sont fusionnées et que ses fichiers ne chevauchent pas ceux d'une tâche en cours. Pour chaque tâche: un agent *test-writer* écrit les tests, puis un agent *worker* implémente; la CI tourne; la fusion est refusée si elle n'est pas verte. Garde-fous: itérations et durée maximales, détection de boucle; **escalade** vers un modèle plus fort après N échecs; tâche `failed` puis dépendantes `blocked` au-delà. Tout l'état est en base: un worker redémarré **reprend** sans rien refaire.

## Décisions d'architecture

Courtes et datées dans [`docs/decisions/`](https://github.com/Installation-04/Cobble/tree/main/docs/decisions) (0001 à 0007).
