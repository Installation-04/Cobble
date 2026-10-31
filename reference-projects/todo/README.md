# Reference project: to-do list

The simplest reference project of the agent bench (PLAN.md section 15). It exercises the whole loop on a very small application: interview, spec, plan, tasks with tests first, CI, demo.

- `spec.md`: the target specification, as the interview should produce it.
- Hidden acceptance tests (kept out of the agents' reach) will be added with the bench in v0.3.

## The idea, in the user's words

> I want a simple to-do list app.
>
> Just for me, on my phone. I want to add tasks, tick them off and delete them. No account needed.

## Scripted flow with cassettes

`providers/fake-llm/cassettes/todo-*.json` replay this exact conversation (English and French) so the loop can be tested and demoed with no model: two interview turns, the spec, a valid plan (3 milestones, 11 tasks of size S or M), and two invalid-plan scenarios for the retry logic. The cassettes are keyed by the exact prompts; after changing a prompt, regenerate them:

```
cd providers/fake-llm && uv run python scripts/make_todo_cassettes.py
```

## Résumé (français)

Projet de référence le plus simple du banc d'essai: une liste de tâches personnelle (ajouter, cocher, supprimer; sans compte; pour téléphone). `spec.md` est la spécification visée. Les cassettes `todo-*.json` du faux fournisseur rejouent le flux complet (entrevue en deux tours, spécification, plan valide, plans invalides pour tester les reprises) en français et en anglais; la commande ci-dessus les régénère après un changement de prompt.
