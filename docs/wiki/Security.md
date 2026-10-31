# Security

**English** · [Français](#français)

Generated code is treated as **untrusted** and runs isolated.

## Coding agents

- **Non-root** container, **no Docker socket**, no Linux capabilities, `no-new-privileges`.
- **CPU, memory, process and time** limits; **read-only** root filesystem, only the task's worktree is writable.
- **Network**: an internal network whose only exit is an **allowlist proxy** (the internal API and package registries). No direct Internet access.
- **No Git credentials inside the container**: the pack service clones and pushes outside it, from a bare copy (the `.git` written by the agent is never executed).
- Model calls use a **signed, expiring token** bound to a project, a task and a role.

## Who touches Docker?

Only the **pack services** (agent-service, preview service) mount the Docker socket. The core (API, worker) never does.

## Authentication and network

A single admin account, created from a single-use link (hashed in the database, valid 24 h). Passwords use `scrypt`. Sessions are opaque tokens in an `HttpOnly`, `SameSite=Lax` cookie, with an anti-CSRF header on every state-changing request and login rate limiting. Caddy is the only published port.

## Supply chain

Docker images **pinned by digest**, **locked** dependencies, **generated** secrets (never in code, logs or cassettes). Generated projects run **Semgrep**, **Trivy** and **Gitleaks** in CI.

## Demos

Previews run in a non-root container with no published port, on an internal network, and stop when idle. The preview embedded in the UI is sandboxed; for a demo that calls its own API, open it in a new tab.

## Reporting a vulnerability

Do not open a public issue: use GitHub's **private security advisories**. See [SECURITY.md](https://github.com/Installation-04/Cobble/blob/main/SECURITY.md).

---

## Français

Le code généré est considéré comme **non fiable** et s'exécute isolé.

## Agents de code

- Conteneur **non-root**, **sans socket Docker**, sans capacités Linux, `no-new-privileges`.
- Limites **CPU, mémoire, nombre de processus et durée**; système de fichiers racine **en lecture seule**, seul le dossier de travail de la tâche est inscriptible.
- **Réseau**: un réseau interne dont la seule sortie est un **proxy à liste blanche** (l'API interne et les registres de paquets). Pas de sortie Internet directe.
- **Aucun identifiant Git dans le conteneur**: c'est le service de pack qui clone et pousse, hors du conteneur, avec une copie nue du dépôt (le `.git` écrit par l'agent n'est jamais exécuté).
- Appels de modèle par **jeton signé à durée limitée**, lié à un projet, une tâche et un rôle.

## Qui touche Docker ?

Seuls les **services de pack** (agent-service, service d'aperçu) montent le socket Docker. Le noyau (API, worker) n'y touche jamais.

## Authentification et réseau

Un seul compte admin, créé par lien à usage unique (haché en base, 24 h). Mots de passe en `scrypt`. Sessions par jeton opaque dans un cookie `HttpOnly`/`SameSite=Lax`, avec en-tête anti-CSRF sur toute requête modifiante, et limitation des tentatives de connexion. Seul Caddy publie un port.

## Chaîne d'approvisionnement

Images Docker **épinglées par digest**, dépendances **verrouillées**, secrets **générés** (jamais dans le code, les journaux ni les cassettes). La CI des projets générés inclut **Semgrep**, **Trivy** et **Gitleaks**.

## Démos

Les aperçus tournent dans un conteneur non-root, sans port publié, sur un réseau interne, avec arrêt après inactivité. L'aperçu intégré à l'interface est sandboxé; pour une démo qui appelle sa propre API, ouvrez-la dans un nouvel onglet.

## Signaler une faille

Pas d'issue publique: utilisez les **avis de sécurité privés** de GitHub. Voir [SECURITY.md](https://github.com/Installation-04/Cobble/blob/main/SECURITY.md).
