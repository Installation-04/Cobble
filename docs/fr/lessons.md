# Leçons apprises

Quand une tâche échoue à répétition dans un projet, Cobble garde une courte note de la cause et la communique aux prochains agents du même projet, pour qu'ils ne refassent pas l'erreur ([ADR 0026](../decisions/0026-lessons-learned.md)). Aucun modèle n'est appelé pour les écrire : elles ne coûtent rien en elles-mêmes.

## Ce qui est retenu

Une leçon est enregistrée quand une tentative d'agent échoue et que la tâche a déjà échoué autant de fois qu'il en faut pour passer au modèle d'escalade (2 par défaut) :

- **Échec de la CI** : le premier test en échec et son message.
- **Boucle** : la ligne que l'agent répétait.
- **Délai dépassé** : la dernière chose affichée avant la fin du temps imparti.

Les textes sont en clair, de 300 caractères au plus, et les secrets (jetons, mots de passe, clés) sont masqués. La même erreur revue ne fait qu'augmenter son compteur. Un projet garde au plus 20 leçons actives; au-delà, la moins utile des leçons automatiques est supprimée (celles que vous écrivez ne le sont jamais).

## Ce que voient les agents

Les exécutions du rédacteur de tests et de l'implémenteur du projet reçoivent un court bloc « Lessons from this project » avec au plus 5 leçons actives (les plus revues d'abord, puis les plus récentes), environ 300 jetons au maximum. Un projet sans leçon n'ajoute rien.

## Les gérer

Ouvrez le projet, onglet **Agents**, section **Leçons apprises**. Vous pouvez ajouter une leçon, modifier son texte, la désactiver (conservée mais non montrée aux agents) ou la supprimer. Un badge indique celles que le prochain agent verra.

API (mêmes règles de propriété et de CSRF que les autres routes) : `GET` et `POST /api/v1/projects/{id}/lessons`, `PATCH` et `DELETE /api/v1/projects/{id}/lessons/{lesson_id}`. `409 lessons_full` quand 20 sont déjà actives.
