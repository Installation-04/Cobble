# API de facturation

Un petit service de facturation pour un travailleur autonome. Des clients, des factures avec lignes et taxe, et un statut qui suit la facture du brouillon au paiement. Ni compte ni connexion.

## Fonctionnalités
- Clients: nom (1 à 100 caractères) et courriel (doit ressembler à une adresse courriel). Les lister, en lire un, en supprimer un. Un client qui a des factures ne peut pas être supprimé.
- Factures: pour un client, un taux de taxe et au moins une ligne. Une ligne a une description (1 à 100 caractères), une quantité (entier, au moins 1) et un prix unitaire.
- **L'argent est exact.** Les prix sont envoyés et renvoyés en chaînes avec exactement deux décimales (`"19.99"`); un prix avec plus de deux décimales, un prix négatif ou une valeur non numérique est refusé. Ne jamais calculer les montants en virgule flottante binaire.
- Le montant d'une ligne est la quantité multipliée par le prix unitaire. Le sous-total est la somme des montants des lignes. La taxe est le sous-total multiplié par le taux de taxe (un pourcentage entre 0 et 100, 0 par défaut, envoyé comme nombre JSON, par exemple `5.5`), **arrondie à la demie supérieure à deux décimales** (0,005 devient 0,01). Le total est le sous-total plus la taxe. Tous sont renvoyés en chaînes à deux décimales.
- Chaque facture a un numéro `INV-0001`, `INV-0002`... attribué dans l'ordre de création. Un numéro n'est jamais réutilisé, même si la facture portant le plus grand numéro est supprimée.
- Statut: une nouvelle facture est un `draft`. `send` fait passer un brouillon à `sent`; `pay` fait passer une facture envoyée à `paid`. Tout autre passage est refusé avec 409.
- Seul un brouillon peut être modifié (taux de taxe et lignes; les totaux sont recalculés) ou supprimé. Le reste est refusé avec 409.
- Lister les factures par ordre de numéro, avec filtres facultatifs `?status=` et `?customer_id=`.
- Un rapport de synthèse: pour chacun de `draft`, `sent`, `paid`, le nombre de factures et la somme de leurs totaux; plus `outstanding`, la somme des totaux restant à payer (les factures `sent`).

## Écrans
- Une page pour créer des clients et des factures, voir la liste des factures avec leur statut, et les envoyer ou les marquer payées.

## Modèle de données
- Client: id, name, email.
- Facture: id, number, customer_id, status, tax_rate, lines (description, quantity, unit_price, amount), subtotal, tax, total.

## Contraintes
- Backend FastAPI, données conservées sur disque (elles survivent à un redémarrage).
- Utilisable sur un écran de téléphone.

## Hors périmètre
- Plusieurs devises, PDF, envoi de courriels, plusieurs taux de taxe par facture, authentification.

## Critères d'acceptation
- `GET /api/health` répond 200.
- `POST /api/customers`, `GET /api/customers`, `GET /api/customers/{id}`, `DELETE /api/customers/{id}` (201, 200, 200 ou 404, 204 ou 409).
- `POST /api/invoices` (201; 404 pour un client inconnu; 422 pour des champs invalides), `GET /api/invoices`, `GET /api/invoices/{id}`, `PATCH /api/invoices/{id}`, `DELETE /api/invoices/{id}`.
- `POST /api/invoices/{id}/send` et `POST /api/invoices/{id}/pay` répondent 200 avec la facture, 409 pour un passage interdit, 404 si inconnue.
- `GET /api/reports/summary` répond `{"draft": {"count", "total"}, "sent": {...}, "paid": {...}, "outstanding": "..."}`.
