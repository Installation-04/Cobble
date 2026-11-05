# Robot conversationnel simple

Un petit robot conversationnel à règles pour un site web. Il salue, répond aux mots-clés que son propriétaire configure, fait des calculs simples et garde l'historique des conversations. Aucun modèle de langage à l'intérieur: les réponses viennent de règles fixes. Ni compte ni connexion.

Les textes de réponse ci-dessous sont en anglais et doivent être reproduits à la lettre.

## Fonctionnalités
- **Envoyer un message**: `user` (1 à 30 caractères) et `text` (1 à 500 caractères). La réponse est `{"reply": "..."}`. Chaque message et sa réponse sont conservés dans l'historique.
- Un texte qui commence par `/` est une **commande** (le nom de la commande ne tient pas compte de la casse, le reste du texte est pris tel quel). Les règles et les salutations ne s'appliquent jamais aux commandes.
  - `/help` répond `Commands: /help, /echo, /calc, /count`.
  - `/echo <texte>` répond exactement `<texte>`, tout ce qui suit le premier espace. Sans texte, il répond `Usage: /echo <text>`.
  - `/calc <expression>` calcule une expression avec des nombres décimaux, `+`, `-`, `*`, `/`, des parenthèses et un signe moins devant un nombre ou une parenthèse, avec les priorités habituelles. La réponse est le résultat: un entier sans décimales (`14`), sinon au plus 6 décimales sans zéros à la fin (`2.5`, `0.333333`). Une division par zéro répond `Error: division by zero`. Tout ce qui ne peut pas être lu répond `Error: invalid expression`. L'expression ne doit jamais être exécutée comme du code.
  - `/count` répond combien de messages cet utilisateur a envoyés, **celui-ci compris**: `You have sent 1 message.` ou `You have sent 3 messages.`
  - Toute autre commande répond `Unknown command: /nom. Try /help.` (avec la commande telle que tapée, en minuscules).
- Sinon le robot examine les **règles de mots-clés**, dans l'ordre de leur création. Une règle correspond quand son mot-clé apparaît dans le texte comme mot entier, sans tenir compte de la casse (`price` correspond à `What is the PRICE?` mais pas à `pricey`). La première règle qui correspond donne sa réponse.
- Si aucune règle ne correspond et que le texte contient l'un des mots entiers `hello`, `hi`, `bonjour`, `salut` (sans tenir compte de la casse), la réponse est `Hello <user>!`.
- Sinon la réponse est `Sorry, I did not understand. Try /help.`
- **Règles**: en créer une avec un `keyword` (1 à 30 caractères) et un `reply` (1 à 200 caractères); deux règles ne peuvent pas avoir le même mot-clé (sans tenir compte de la casse, 409). Les lister dans l'ordre de création. En supprimer une.
- **Historique**: les messages avec leurs réponses, du plus ancien au plus récent, pour un `user` facultatif, limités aux `limit` derniers messages (50 par défaut, de 1 à 200), toujours du plus ancien au plus récent.

## Écrans
- Une page de clavardage: la conversation, une zone de texte et une petite zone d'administration pour ajouter et retirer des règles de mots-clés.

## Modèle de données
- Message: user, text, reply, timestamp (UTC, `YYYY-MM-DDTHH:MM:SSZ`).
- Règle: id, keyword, reply.

## Contraintes
- Backend FastAPI, données conservées sur disque (elles survivent à un redémarrage).
- Utilisable sur un écran de téléphone.

## Hors périmètre
- Modèles de langage, comptes, plusieurs canaux, messages planifiés.

## Critères d'acceptation
- `GET /api/health` répond 200.
- `POST /api/messages` répond 200 avec la réponse (422 pour des champs invalides).
- `POST /api/rules` (201, 409 pour un mot-clé en double, 422 pour des champs invalides), `GET /api/rules`, `DELETE /api/rules/{id}` (204, 404 si inconnue).
- `GET /api/history?user=&limit=`.
