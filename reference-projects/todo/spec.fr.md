# Liste de tâches simple

Une liste de tâches personnelle utilisée depuis un téléphone. Un seul utilisateur, aucun compte.

## Fonctionnalités
- Ajouter une tâche avec un titre.
- Lister toutes les tâches, de la plus ancienne à la plus récente.
- Cocher une tâche comme faite, ou la décocher.
- Supprimer une tâche.

## Écrans
- Une seule page: un formulaire pour ajouter une tâche, puis la liste.
- Chaque tâche a une case à cocher et un bouton de suppression.

## Modèle de données
- Todo: id (entier), title (texte, 1 à 200 caractères), done (booléen, faux par défaut).

## Contraintes
- Backend FastAPI avec une page web simple; les données survivent à un redémarrage.
- Utilisable sur un écran de téléphone (375 px de large).

## Hors périmètre
- Comptes, partage, dates d'échéance, catégories, notifications.

## Critères d'acceptation
- `GET /api/health` répond 200.
- `POST /api/todos` avec un titre répond 201 et renvoie la tâche; un titre vide répond 422.
- `GET /api/todos` liste les tâches de la plus ancienne à la plus récente.
- `PATCH /api/todos/{id}` avec `done` la met à jour; `DELETE /api/todos/{id}` répond 204; un id inconnu répond 404.
- `GET /` sert la page.
