# Architecture

**Français** · [English](#english)

## Vue d'ensemble

```
 Navigateur ──HTTP──▶ Caddy ──▶ UI (React) · API (FastAPI) ──▶ Postgres · Redis
                                          │
                  worker ─▶ planner · ordonnanceur ─▶ routeur de coûts ─▶ LiteLLM ─▶ modèles
                                          │
        service de pack (seul à toucher Docker) ─▶ agents Aider isolés · Forgejo · Woodpecker · aperçus
```

- **Caddy** est le seul service qui publie un port; tout le reste est sur des réseaux internes.
- **API** (FastAPI, `/api/v1`, OpenAPI): authentification, projets, chat, spec, plan, tâches, jalons, coûts. Les erreurs sont des **codes** traduits par l'interface.
- **Worker**: exécute les tâches longues (réponse du planner, génération de la spec et du plan) et l'**ordonnanceur**.
- **Redis**: file de tâches et flux d'événements (SSE vers le navigateur). **Postgres**: tout l'état.
- **LiteLLM**: seule porte vers les modèles. Le **routeur de coûts** mappe les rôles (`planner`, `test-writer`, `worker`, `reviewer`) à des modèles, applique le budget et enregistre jetons et coût par tâche.

## Capacités, pas produits

Le noyau ne nomme jamais Forgejo, Woodpecker, Ollama ni Aider: il utilise `GitProvider`, `CIProvider`, `AgentRunner`, `LLMClient`, `PreviewProvider`. Le **pack fixe v0.1** les implémente: Forgejo (Git), Woodpecker (CI avec Semgrep, Trivy, Gitleaks), Aider (agents), un service d'aperçu. Un test automatique interdit les noms de produits dans le noyau.

## Le cycle d'un projet

Phases: `interview → spec_review → plan_review → ready → building → done`. Le plan est validé par un **schéma strict** (aucune tâche sans critère d'acceptation, taille S ou M seulement, dépendances sans cycle).

**Ordonnanceur**: une tâche est lancée quand ses dépendances sont fusionnées et que ses fichiers ne chevauchent pas ceux d'une tâche en cours. Pour chaque tâche: un agent *test-writer* écrit les tests, puis un agent *worker* implémente; la CI tourne; la fusion est refusée si elle n'est pas verte. Garde-fous: itérations et durée maximales, détection de boucle; **escalade** vers un modèle plus fort après N échecs; tâche `failed` puis dépendantes `blocked` au-delà. Tout l'état est en base: un worker redémarré **reprend** sans rien refaire.

## Décisions d'architecture

Courtes et datées dans [`docs/decisions/`](https://github.com/Installation-04/Cobble/tree/main/docs/decisions) (0001 à 0007).

---

## English

**Overview**: Caddy is the only service publishing a port. The FastAPI API (`/api/v1`, OpenAPI) handles auth, projects, chat, spec, plan, tasks, milestones and costs (errors are **codes** translated by the UI). The worker runs long jobs and the **scheduler**. Redis carries the job queue and event streams (SSE to the browser); Postgres holds all state. **LiteLLM** is the only door to models; the **cost router** maps roles to models, enforces the budget and records tokens and cost per task.

**Capabilities, not products**: the core never names Forgejo, Woodpecker, Ollama or Aider; it uses `GitProvider`, `CIProvider`, `AgentRunner`, `LLMClient`, `PreviewProvider`. The fixed v0.1 pack implements them (Forgejo, Woodpecker with Semgrep/Trivy/Gitleaks, Aider agents, a preview service). A test forbids product names in the core.

**Project lifecycle**: `interview → spec_review → plan_review → ready → building → done`. The plan is validated by a strict schema. The scheduler starts a task when its dependencies are merged and its files do not overlap a running task; a test-writer agent writes the tests, then a worker agent implements; CI runs and the merge is refused unless green. Guardrails: max iterations and duration, loop detection, escalation to a stronger model after N failures. All state is in the database, so a restarted worker resumes without redoing anything. Architecture decisions: [`docs/decisions/`](https://github.com/Installation-04/Cobble/tree/main/docs/decisions).
