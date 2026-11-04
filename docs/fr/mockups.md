# Variantes de maquette

Avant la génération du plan, l'assistant peut dessiner **2 ou 3 maquettes différentes** de votre
écran principal, pour quelques sous. Vous en choisissez une; le plan la suit ensuite. Corriger
une maquette coûte beaucoup moins cher que corriger du code.

## Utilisation

1. Dans le projet, ouvrez l'onglet **Plan** une fois la spécification approuvée.
2. Cochez **Comparer des maquettes avant le plan** (désactivé par défaut).
3. Cliquez sur **Proposer des maquettes**. Deux ou trois cartes apparaissent côte à côte, chacune
   avec un titre, une courte description et un schéma en texte.
4. Cliquez sur **Choisir celle-ci** pour la maquette que vous préférez. Vous pouvez demander
   **d'autres maquettes** autant de fois que vous voulez (un nouveau lot remplace l'ancien et le
   choix).
5. Générez le plan. Tant que l'option est active, le plan ne peut pas être généré sans maquette
   choisie; décochez l'option pour sauter cette étape.

Les schémas sont des dessins en texte brut. Ils ne sont jamais exécutés ni interprétés comme une
page web: rien de ce qu'un modèle écrit ne peut s'exécuter.

## API

| Requête | Effet |
|---|---|
| `PATCH /api/v1/projects/{id}` `{"mockups_enabled": true}` | Active ou désactive l'option. |
| `GET /api/v1/projects/{id}/mockups` | Les variantes (`id`, `position`, `title`, `summary`, `wireframe`, `chosen`). |
| `POST /api/v1/projects/{id}/mockups/generate` `{"count": 3, "feedback": "…"}` | Met la tâche en file (`202`). `count` vaut 2 ou 3. Demande l'option active et une spécification approuvée (`409 mockups_disabled` / `wrong_phase`). |
| `POST /api/v1/projects/{id}/mockups/{variant_id}/choose` | Marque exactement une variante comme choisie. |

La progression arrive sur le flux du projet: `job.started` / `job.failed` (type `mockups`) et
`mockups.updated`. L'appel passe par le routeur de coûts (rôle `planner`) et compte dans les
coûts du projet. Notes de conception: `docs/decisions/0018-mockup-variants.md`.
