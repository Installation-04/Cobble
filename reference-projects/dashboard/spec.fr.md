# Tableau de bord de métriques

De petits services envoient des mesures («événements») à cette application. Une personne consulte les totaux, les moyennes et l'évolution dans le temps. Ni compte ni connexion.

## Fonctionnalités
- Enregistrer un événement: `name` (1 à 50 caractères, seulement des minuscules, des chiffres, `_` et `.`), `value` (un nombre), `source` (1 à 50 caractères, `"default"` si absente) et `timestamp` (date et heure ISO 8601; maintenant si absente). L'horodatage est **converti en UTC** et renvoyé sous la forme `YYYY-MM-DDTHH:MM:SSZ` (`2026-03-05T12:15:00+02:00` devient `2026-03-05T10:15:00Z`). Un horodatage qui n'est pas une date ISO 8601 valide est refusé.
- Lister les métriques (noms d'événements distincts) avec leur nombre d'événements, triées par nom.
- **Synthèse** d'une métrique: `count`, `sum`, `min`, `max` et `avg` (la moyenne arrondie à deux décimales). Plage facultative `from` et `to` (ISO 8601): `from` est inclus, `to` est exclu. Une plage vide donne `count` 0, `sum` 0 et `null` pour `min`, `max` et `avg`. Une métrique inconnue (aucun événement) donne 404; une plage invalide donne 422.
- **Série** d'une métrique: les événements regroupés par tranches d'une `hour` ou d'un `day` (par défaut `day`), en UTC, par ordre croissant, avec la même plage `from`/`to`. Seules les tranches qui ont des événements apparaissent. Chaque tranche donne son `start` (`2026-03-05T00:00:00Z`), `count`, `sum` et `avg`.
- **Meilleures sources** d'une métrique: les sources dont la somme est la plus grande, la plus grande d'abord (égalités par nom de source), au plus `limit` (3 par défaut, de 1 à 20).
- Supprimer tous les événements d'une métrique.

## Écrans
- Une page de tableau de bord: la liste des métriques et, pour la métrique choisie, sa synthèse, un graphique simple de la série et ses meilleures sources.

## Modèle de données
- Événement: id, name, value, source, timestamp.

## Contraintes
- Backend FastAPI, données conservées sur disque (elles survivent à un redémarrage).
- Utilisable sur un écran de téléphone.

## Hors périmètre
- Alertes, authentification, plusieurs tableaux de bord, exports.

## Critères d'acceptation
- `GET /api/health` répond 200.
- `POST /api/events` répond 201 avec l'événement (422 pour des champs invalides). `DELETE /api/events?name=x` répond `{"deleted": n}`.
- `GET /api/metrics` liste `[{"name", "count"}]`.
- `GET /api/metrics/{name}/summary?from=&to=`, `GET /api/metrics/{name}/series?bucket=&from=&to=`, `GET /api/metrics/{name}/top-sources?limit=`.
