# Blogue personnel

Un petit blogue pour un seul auteur. Les lecteurs lisent les articles et laissent des commentaires. Ni compte ni connexion: les actions de l'auteur sont ouvertes (le blogue tourne sur une machine privée).

## Fonctionnalités
- Écrire un article: titre (1 à 120 caractères), corps (non vide), étiquettes (liste facultative, 5 au plus, chacune faite de lettres minuscules et de chiffres seulement) et `published` (booléen, faux par défaut: un nouvel article est un brouillon).
- Chaque article a un **slug** tiré de son titre: minuscules, accents retirés (`é` devient `e`), chaque suite de caractères qui ne sont ni lettres ni chiffres devient un seul trait d'union, aucun trait d'union au début ni à la fin. Quand le slug est déjà pris, ajouter `-2`, puis `-3`, etc. Modifier un article ne change jamais son slug.
- Lister les articles publiés, du plus récent au plus ancien. `?tag=python` ne garde que les articles portant cette étiquette. Les brouillons n'apparaissent jamais dans cette liste.
- Lire un article par son slug. Un brouillon n'est pas public: le lire répond 404.
- Lister les brouillons (pour l'auteur), du plus récent au plus ancien.
- Modifier un article (titre, corps, étiquettes) et publier un brouillon.
- Supprimer un article: ses commentaires partent avec lui et son slug redevient libre.
- Les lecteurs commentent un article publié: auteur (1 à 50 caractères) et corps (1 à 1000 caractères). Les commentaires sont listés du plus ancien au plus récent. Un brouillon ne peut pas être commenté.

## Écrans
- Une page d'accueil avec les articles publiés et un filtre par étiquette.
- Une page pour un article avec ses commentaires et un formulaire de commentaire.
- Une page simple pour que l'auteur écrive, publie et supprime des articles.

## Modèle de données
- Article: slug, title, body, tags (liste de textes), published (booléen), created_at (date et heure ISO 8601), comment_count (entier).
- Commentaire: author, body, created_at.

## Contraintes
- Backend FastAPI, données conservées sur disque (elles survivent à un redémarrage).
- Utilisable sur un écran de téléphone.

## Hors périmètre
- Comptes, images, rendu Markdown, recherche, RSS, notifications.

## Critères d'acceptation
- `GET /api/health` répond 200.
- `POST /api/posts` crée un article (201, l'article en JSON avec tous ses champs); des champs invalides répondent 422.
- `GET /api/posts` (publiés, du plus récent au plus ancien, `tag` facultatif), `GET /api/drafts`, `GET /api/posts/{slug}` (404 pour un brouillon ou un slug inconnu).
- `PATCH /api/posts/{slug}` modifie titre, corps, étiquettes et `published` (404 si inconnu). `DELETE /api/posts/{slug}` répond 204 (404 si inconnu).
- `POST /api/posts/{slug}/comments` répond 201 (404 pour un article inconnu ou brouillon, 422 pour des champs invalides); `GET /api/posts/{slug}/comments` les liste du plus ancien au plus récent.
