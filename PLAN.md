# Cobble — Plan de développement

> Plan destiné à Claude Code. Lire au complet avant de commencer, puis travailler version par version (section Feuille de route).

## 1. Vision

Une plateforme libre et auto-hébergée qui transforme une idée en application fonctionnelle, au coût le plus bas possible.

L'utilisateur décrit son idée dans un chat. Un modèle fort l'aide à préciser le besoin et produit un plan. Des agents peu coûteux (modèles locaux ou API à bas prix) exécutent les tâches dans des conteneurs isolés, encadrés par des tests et une CI qui tournent en continu. À la fin, l'utilisateur valide une démo.

Toute l'infrastructure (Git, CI, modèles locaux, observabilité…) s'installe depuis un **magasin de modules** intégré, dans l'esprit de Project NOMAD, CasaOS ou Umbrel: un clic, Docker roule en arrière-plan, et tout se configure et se relie automatiquement.

### Pour qui
- **Particuliers et makers** qui ont des idées d'applications sans budget de développement.
- **Homelabbers** qui ont déjà un serveur Proxmox ou un PC avec GPU.
- **Consultants et petites équipes** qui livrent du logiciel sur mesure et veulent contrôler leurs coûts.

### Ce que le projet n'est pas
- Pas un remplaçant d'un développeur pour des systèmes critiques: la plateforme livre des démos validées, l'utilisateur reste responsable de ce qu'il met en production.
- Pas un service hébergé: chacun l'installe chez lui.

## 2. Principes

1. **Simple d'abord**: l'utilisateur ne voit jamais un fichier compose, un port ou un jeton d'API. Tout ce qui peut être deviné ou généré l'est.
2. **Le moins cher qui fonctionne**: chaque appel à un modèle passe par le routeur de coûts; le modèle le plus cher n'est utilisé que lorsque le moins cher a échoué ou pour planifier.
3. **Les tests sont l'arbitre**: un agent n'a jamais « fini » parce qu'il le dit, mais parce que les critères d'acceptation passent en CI. C'est ce qui rend les petits modèles utilisables.
4. **Modulaire par capacités**: le noyau parle à des capacités (`git`, `ci`, `llm`, `agent-runner`…), jamais à un produit précis.
5. **Zéro conflit par construction**: ports, noms, réseaux, volumes et secrets sont gérés par la plateforme, pas par l'utilisateur.
6. **Local d'abord, hors ligne possible**: tout doit pouvoir rouler sans Internet une fois les modèles et images téléchargés.
7. **Sécurité par défaut**: le code généré est considéré comme non fiable et roule isolé.
8. **Bilingue dès le départ**: interface et documentation en français et en anglais.

## 3. Concepts

| Concept | Définition |
|---|---|
| **Projet** | Une application à construire: un dépôt Git, un budget, un historique de chat, une démo. |
| **Spec** | Le besoin validé par l'utilisateur (fonctionnalités, écrans, contraintes), produit par l'entrevue initiale. |
| **Plan** | La spec découpée en jalons et en tâches avec dépendances. |
| **Tâche** | Unité de travail d'un agent, avec des critères d'acceptation testables et une liste de fichiers visés. |
| **Agent** | Un conteneur éphémère qui exécute une tâche avec un modèle donné. |
| **Capacité** | Un rôle d'infrastructure (`git`, `ci`, `llm`, `agent-runner`, `observability`, `preview`, `notify`, `sandbox`). |
| **Module** | Un paquet installable du magasin qui fournit une ou plusieurs capacités. |
| **Nœud** | Une machine qui contribue de la puissance (GPU, agents) à une installation principale. |

## 4. Architecture

```
┌────────────────────────────── Interface web ──────────────────────────────┐
│  Projets / Chat  │  Agents  │  Démos  │  Magasin  │  Coûts  │  Réglages    │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ HTTPS (Caddy)
┌─────────────────────────────────────┴─────────────────────────────────────┐
│                                   NOYAU                                    │
│  API (FastAPI)          Orchestrateur        Planificateur de tâches       │
│  Registre des capacités Routeur de coûts     Gestionnaire de modules       │
│  Bus d'événements (Redis)  Postgres          LiteLLM (passerelle LLM)      │
└──────────┬──────────────────────┬───────────────────────────┬─────────────┘
           │ réseau cobble-bus        │                           │ API nœud
   ┌───────┴──────┐   ┌───────────┴──────────┐      ┌─────────┴──────────┐
   │ Modules      │   │ Agents (éphémères)   │      │ Nœuds distants     │
   │ Forgejo, CI, │   │ un conteneur isolé   │      │ PC GPU, 2e serveur │
   │ Ollama, …    │   │ par tâche            │      │ (llm, agents)      │
   └──────────────┘   └──────────────────────┘      └────────────────────┘
```

### Pile technique proposée
- **Backend**: Python 3.12+, FastAPI, SQLAlchemy + Alembic (migrations), Pydantic.
- **File de tâches et événements**: Redis (streams) avec une librairie simple (arq ou équivalent). Temporal seulement si les workflows deviennent trop complexes.
- **Frontend**: React + Vite, TypeScript, i18n FR/EN intégré, mode clair/sombre.
- **Temps réel**: WebSocket ou SSE pour les logs et l'état des agents.
- **Passerelle LLM**: LiteLLM (version épinglée).
- **Proxy**: Caddy (HTTPS automatique, CA interne pour le réseau local).
- **Module-manager**: Python, dans la même pile que le reste du noyau.

### Contrat d'API
- API REST versionnée (`/api/v1`) documentée en OpenAPI; l'interface web n'utilise que cette API.
- Tous les changements d'état publient un événement (`task.started`, `ci.failed`, `budget.reached`…). L'UI, les notifications et les intégrations s'y abonnent.

## 5. Installation

Une seule commande, sur une machine Ubuntu ou Debian fraîche:

```bash
curl -fsSL https://<domaine>/install.sh | sudo bash
```

Pour les prudents, la documentation offre aussi: télécharger le script, vérifier sa somme SHA-256 et sa signature, le lire, puis l'exécuter.

### Systèmes supportés
- Ubuntu Server 24.04 LTS et 26.04 LTS, Debian 12 et 13 (amd64; arm64 plus tard).
- Proxmox: VM recommandée (passthrough GPU simple). LXC possible en mode privilégié avec `nesting=1` et `keyctl=1`; le script détecte le LXC et avertit si ces options manquent.
- Minimum: 2 vCPU, 4 Go de RAM, 40 Go de disque (sans modèles locaux). Recommandé avec modèles locaux: GPU 12 Go de VRAM ou plus.

### Ce que fait `install.sh`
1. **Vérifications**: root/sudo, OS, architecture, RAM, disque, ports 80/443, accès Internet. Arrêt clair avec la raison si un prérequis manque.
2. **Docker Engine** depuis le dépôt officiel Docker (pas le paquet de la distribution), avec le plugin compose. Réutilise un Docker existant si la version convient.
3. **GPU**: NVIDIA (pilote si absent, NVIDIA Container Toolkit, test `nvidia-smi` en conteneur) ou AMD (`/dev/kfd`, `/dev/dri`, ROCm). Si un redémarrage est requis, le script le dit et reprend là où il était.
4. **Noyau** installé dans `/opt/cobble` (configurable), secrets générés, images épinglées par digest, démarrage.
5. **Service systemd** `cobble` et CLI `cobble`.
6. **Pare-feu**: si `ufw` est actif, ouvre seulement 80/443.
7. **Fin**: affiche l'URL (IP et nom d'hôte) et un lien d'activation à usage unique pour créer le compte admin. Le pack de départ se choisit ensuite dans l'interface.

### Propriétés
- **Idempotent**: relancer répare ou complète, sans rien écraser.
- **Non interactif** au besoin: `install.sh --yes --gpu=nvidia --dir=/opt/cobble`.
- **Journal**: `/var/log/cobble-install.log`.
- **Court et lisible**: la logique lourde vit dans le module-manager, pas dans le bash.

### CLI
`cobble status | logs | update | backup | restore | uninstall [--keep-data] | doctor | reset-admin`

`doctor` vérifie Docker, GPU, disque, certificats et santé des modules, puis propose des correctifs.

### Mises à jour du noyau
- Canaux `stable` et `beta`. Sauvegarde automatique (base + config) avant chaque mise à jour, migrations Alembic, retour en arrière en une commande si le healthcheck échoue.

## 6. Magasin

Le magasin offre quatre types d'éléments, tous installables en un clic:

| Type | Exemples |
|---|---|
| **Modules d'infrastructure** | Forgejo, Woodpecker, Ollama, llama.cpp, vLLM, Langfuse, ntfy, Tailscale |
| **Gabarits de projet** | Web app FastAPI + React, API Node, app mobile Expo, script Python, bot Discord, site statique |
| **Profils d'agents** | « Développeur backend », « Testeur QA », « Réviseur sécurité », « Rédacteur de doc » |
| **Préréglages de modèles** | « Économique local », « Équilibré », « Qualité max », avec les modèles adaptés à chaque matériel |

### Manifeste d'un module

```yaml
id: forgejo
name: Forgejo
version: 9.0.1                 # image épinglée par digest, jamais :latest
category: git
description: { fr: "Serveur Git léger", en: "Lightweight Git server" }
license: GPL-3.0
provides: [git]
requires: []                   # installées automatiquement si absentes
exclusive: [git]               # un seul fournisseur actif de ces capacités
hardware: { min_ram_mb: 512, gpu: none }   # gpu: none | optional | nvidia | amd | any
variants: []                   # ex. ollama: cpu, nvidia, amd
web_ui: { port: 3000, path: /git }         # exposé via Caddy, jamais sur l'hôte
settings:                      # formulaire généré dans l'interface
  - { key: admin_email, type: email, default: "{{ platform.admin_email }}" }
secrets: [admin_password, api_token]       # générés et stockés dans le coffre
healthcheck: { http: /api/healthz, interval: 10s }
integrations:
  ci: hooks/link-ci.sh         # ex. crée l'application OAuth pour la CI
  core: hooks/register-core.sh
backup: { volumes: [data] }
offline: true                  # utilisable sans Internet après installation
```

### Règles anti-conflit (appliquées par le module-manager, jamais laissées au manifeste)
- Aucun port publié sur l'hôte sauf Caddy (80/443); chaque module est exposé par chemin ou sous-domaine.
- Espace de noms par module: projet compose `cobble-<id>`, volumes `cobble-<id>-*`, conteneurs préfixés.
- Un réseau privé par module, plus le réseau `cobble-bus` seulement pour les services qui doivent se parler.
- Secrets générés automatiquement et injectés; l'utilisateur n'en saisit jamais.
- Graphe des dépendances calculé avant l'installation; deux fournisseurs d'une capacité exclusive sont refusés, et l'interface propose de remplacer à la place.
- Matériel vérifié: modules incompatibles grisés avec la raison; la bonne variante est choisie automatiquement.
- Ressources: limites CPU/RAM par défaut par module; la VRAM est réservée et suivie (voir Ordonnancement).

### Branchement automatique
À l'installation: `post-install` → `register-core` → `on-link` avec chaque capacité déjà présente → healthcheck. En cas d'échec, retour en arrière et message clair. À la désinstallation, les hooks inverses débranchent proprement, avec option de garder les données.

Exemples: Forgejo + Woodpecker → application OAuth et webhook créés; Ollama → modèles ajoutés à LiteLLM, rechargement à chaud; Langfuse → clés injectées dans LiteLLM.

### Conteneurs custom
1. **Image Docker**: l'assistant lit l'image (ports `EXPOSE`, volumes, variables), génère le manifeste, l'expose via Caddy et l'isole.
2. **Fichier compose**: importé et réécrit pour respecter les règles (ports hôtes retirés, noms préfixés, réseaux ajoutés).
3. **Module complet**: manifeste écrit à la main pour déclarer des capacités (ex.: un serveur compatible OpenAI déclaré `provides: [llm]` s'enregistre dans LiteLLM).

Les éléments custom ou tiers portent un badge « non vérifié » et n'accèdent pas à `cobble-bus` sans autorisation explicite.

### Packs de départ
Proposés au premier lancement selon le matériel détecté: **Local GPU**, **Local CPU**, **API seulement**, **Nœud GPU distant**. Modifiables ensuite.

### Catalogues
- Un catalogue = un dépôt Git. Le catalogue officiel est inclus; on peut ajouter des catalogues communautaires ou privés.
- Le catalogue officiel publie des combinaisons de versions testées ensemble en CI; une mise à jour qui casse une intégration n'est pas proposée.
- Les dépendances des modules officiels sont tenues à jour automatiquement (Renovate) et passent la CI avant publication.
- Un **miroir hors ligne** du catalogue et des images peut être exporté sur clé USB pour les installations sans Internet.

## 7. Moteur d'agents

C'est le cœur du produit. L'objectif est que des modèles modestes réussissent en leur donnant des tâches petites, précises et vérifiables.

### Étape 1 — Entrevue (modèle `planner`)
- Le planner pose des questions ciblées (public, fonctionnalités, données, plateforme, contraintes) au lieu de deviner.
- Il propose un gabarit de projet du magasin et une pile technique simple.
- Livrable: une **spec** lisible (fonctionnalités, écrans, modèle de données) et, pour les apps avec interface, une **maquette** HTML statique que l'utilisateur peut cliquer. Corriger une maquette coûte beaucoup moins cher que corriger du code.
- L'utilisateur valide la spec avant toute génération de code.

### Étape 2 — Plan et estimation
- La spec devient des jalons, puis des tâches. Chaque tâche suit un schéma strict:

```yaml
id: T-012
title: Endpoint de création de facture
milestone: M2
depends_on: [T-008, T-010]
files: [app/api/invoices.py, app/models/invoice.py, tests/api/test_invoices.py]
acceptance:
  - "POST /api/invoices avec données valides retourne 201 et l'objet créé"
  - "Montant négatif retourne 422"
tests: tests/api/test_invoices.py   # écrit AVANT l'implémentation
size: S                             # S | M (aucune tâche L : on redécoupe)
role: backend
```

- **Tests d'abord**: pour chaque tâche, un agent écrit d'abord les tests à partir des critères, un modèle plus fort les révise rapidement, puis un agent bon marché implémente jusqu'à ce qu'ils passent.
- **Estimation** de tokens, de coût et de durée par jalon, affichée avant le lancement; l'utilisateur approuve un budget.

### Étape 3 — Exécution
- **Ordonnanceur**: lance en parallèle les tâches dont les dépendances sont terminées **et** dont les fichiers ne se chevauchent pas, pour éviter les conflits de fusion. Nombre d'agents simultanés configurable.
- **Contexte minimal**: chaque agent reçoit la tâche, les fichiers visés, une carte du dépôt (repo map) et la mémoire du projet, pas tout le dépôt.
- **Boucle d'un agent**: worktree dédié → code → tests locaux → push de branche → CI → fusion si vert (rebase automatique si la branche principale a bougé).
- **Garde-fous**: nombre maximal d'itérations, durée maximale, détection de boucle (mêmes erreurs répétées, mêmes modifications annulées). Un agent bloqué s'arrête au lieu de brûler des tokens.
- **Escalade**: après N échecs, la tâche monte au modèle supérieur; si elle échoue encore, elle est redécoupée par le planner ou envoyée à l'utilisateur.
- **Questions à l'humain**: un agent peut déposer une question dans une file (« Le montant doit-il inclure les taxes? ») au lieu d'inventer; les autres tâches continuent pendant ce temps.
- **Révision**: un agent réviseur relit chaque fusion d'un jalon (cohérence, sécurité de base, conventions).

### Étape 4 — Démo et validation
- À chaque jalon, une démo est déployée automatiquement (sous-domaine via Caddy) avec captures d'écran prises par un agent QA (Playwright).
- L'utilisateur accepte, commente (les commentaires deviennent de nouvelles tâches) ou revient au jalon précédent (tags Git).

### Mémoire de projet
- Un fichier `PROJECT.md` dans chaque dépôt: décisions, conventions, pile, glossaire. Lu par tous les agents, mis à jour par le planner.
- **Leçons apprises** globales: les erreurs récurrentes, tous projets confondus, deviennent des règles ajoutées au contexte des agents.

### Secrets des projets générés
- Les applications générées qui ont besoin de clés (paiement, courriel…) utilisent des variables d'environnement; les agents ne voient que des valeurs factices. Les vraies valeurs sont injectées seulement dans la démo, depuis le coffre.

## 8. Contrôle des coûts

- **Rôles de modèles**: `planner`, `test-writer`, `worker`, `reviewer`, `escalation`; chaque rôle a une chaîne de repli (ex.: local → API économique → API forte).
- **Budget par projet** avec plafond dur: pause automatique et notification à 80 % et 100 %.
- **Tableau des coûts** par projet, jalon, tâche et modèle, en dollars et en tokens; pour le local, estimation de l'électricité (puissance du GPU × temps × tarif saisi).
- **Cache de prompts** activé quand le fournisseur le supporte; contexte réduit au strict nécessaire.
- **Benchmark local**: à l'installation et à l'ajout d'un modèle, une petite suite de tâches de code mesure la qualité et la vitesse sur ce matériel, puis choisit le meilleur `worker` automatiquement.
- **Mode nuit**: les tâches non urgentes attendent une plage horaire (GPU libre, électricité moins chère).

## 9. Ordonnancement des ressources

- Le planificateur connaît la VRAM et la RAM disponibles par nœud; il ne lance pas un modèle qui ne rentre pas et charge/décharge les modèles selon la file d'attente.
- Les démos des projets ont des limites de ressources et s'arrêtent après une période d'inactivité.
- Priorités: le chat et la planification passent avant les tâches d'agents en arrière-plan.

## 10. Nœuds distants

Généralise l'idée « Ollama sur une autre machine »:
- Un PC avec GPU (ou un deuxième serveur) installe l'**agent de nœud** avec `install.sh --node --join <jeton>`.
- Le nœud annonce ses capacités (GPU, VRAM, `llm`, `agent-runner`) à l'installation principale, qui l'utilise automatiquement.
- Connexion chiffrée (mTLS ou Tailscale); un nœud qui se déconnecte voit ses tâches reprises ailleurs.
- Exemple: le serveur Proxmox héberge le noyau et Forgejo, le PC de jeu prête son GPU le soir.

## 11. Sécurité

- **Agents**: conteneurs sans privilèges, système de fichiers en lecture seule sauf le worktree, limites CPU/RAM/PID/durée, réseau restreint (seulement LiteLLM, Git et les registres de paquets via un proxy en liste blanche).
- **Isolation renforcée** en module optionnel: gVisor (`runsc`) pour les agents; Sysbox si un agent doit exécuter Docker (sans `--privileged`).
- **Module-manager**: seul service avec accès au socket Docker; non exposé au réseau, appelé uniquement par l'API interne authentifiée.
- **Authentification dès la v0.1**, même en mode un seul utilisateur; HTTPS partout (CA interne pour le réseau local, Let's Encrypt avec un domaine, ou Tailscale).
- **Chaîne d'approvisionnement**: images épinglées par digest, images du projet signées (cosign) avec SBOM, script d'installation signé avec somme de contrôle publiée.
- **CI des projets générés**: Semgrep, Trivy (dépendances), Gitleaks (secrets) inclus par défaut dans les gabarits.
- **Journal d'audit**: qui a installé quoi, quelle tâche a modifié quoi, quels appels LLM ont coûté combien.
- `SECURITY.md` avec processus de divulgation responsable.

## 12. Interface

### Apparence et disposition (inspirée d'Open WebUI)

L'interface reprend l'ergonomie d'Open WebUI, que beaucoup d'utilisateurs de modèles locaux connaissent déjà, mais **sans réutiliser son code** (licence avec restrictions de marque). Le code est maison, en React + Tailwind CSS + composants shadcn/ui (Radix), ce qui donne le même style épuré.

```
┌──────────────┬──────────────────────────────────────────────────────────┐
│ ☰  Cobble    │  [Projet: Facturation ▾]   [Préréglage: Équilibré ▾]  ⚙ 👤 │
│              ├──────────────────────────────────────────────────────────┤
│ + Nouveau    │                                                          │
│ 🔍 Recherche │        Fil de conversation (Markdown, code, maquettes,  │
│              │        cartes de plan, cartes de tâches cliquables)     │
│ 📁 Clients   │                                                          │
│   ├ Facturat.│                                                          │
│   └ Inventai.│                                                          │
│ 📁 Perso     │                                                          │
│   └ Recettes │  ┌────────────────────────────────────────────────────┐ │
│              │  │ Décris ton idée…               📎  🎤   ➤          │ │
│ ─────────    │  └────────────────────────────────────────────────────┘ │
│ 🤖 Agents  3 ├──────────────────────────────────────────────────────────┤
│ 🖥 Démos     │  Onglets du projet: Chat · Plan · Agents · Démo · Coûts  │
│ 🧩 Magasin   │                                                          │
│ 💲 Coûts     │                                                          │
└──────────────┴──────────────────────────────────────────────────────────┘
```

- **Barre latérale gauche** repliable: nouveau projet, recherche, projets classés en **dossiers** (glisser-déposer, épingler, archiver), puis accès aux vues globales (Agents, Démos, Magasin, Coûts) avec des pastilles d'état (ex.: nombre d'agents actifs).
- **Barre du haut**: sélecteur de projet, sélecteur de **préréglage de modèles** (comme le sélecteur de modèle d'Open WebUI), réglages et profil.
- **Zone centrale**: chat plein écran, rendu Markdown, coloration du code, maquettes et diffs intégrés, cartes de plan et de tâches cliquables.
- **Champ de saisie**: pièces jointes (croquis, captures, fichiers), dictée vocale, envoi; `/` ouvre des commandes rapides (`/plan`, `/budget`, `/demo`, `/pause`).
- **Réglages** en fenêtre modale à onglets: Général, Apparence, Modèles, Nœuds, Clés d'API, Utilisateurs, Sauvegardes, À propos.
- **Raccourcis clavier** (nouveau projet, recherche, basculer la barre latérale, palette de commandes `Ctrl/Cmd+K`).
- **Responsive**: sur téléphone, la barre latérale devient un tiroir et les onglets passent en bas de l'écran (PWA).

### Mode sombre
- Trois choix: **Système** (par défaut, suit le système d'exploitation), **Clair**, **Sombre**. Changement instantané, sans recharger.
- Couleurs définies par des jetons de thème (variables CSS) pour que les deux modes soient cohérents partout, y compris les blocs de code, les diffs, les graphiques de coûts et les maquettes.
- Contrastes vérifiés WCAG AA dans les deux modes (test automatisé dans la CI).

### Bilinguisme
- **Français et anglais complets dès la v0.1**: interface, messages d'erreur, courriels et notifications, CLI, installateur et documentation.
- Langue détectée depuis le navigateur au premier lancement, puis choisie par utilisateur dans son profil; bascule FR/EN accessible en un clic.
- Toutes les chaînes passent par des fichiers de traduction (react-i18next côté web, gettext ou équivalent côté Python); la CI échoue si une clé manque dans une des deux langues.
- Formats régionaux respectés: dates, nombres, devises (`1 234,56 $` en français, `$1,234.56` en anglais).
- **Les agents répondent dans la langue de l'utilisateur**: entrevue, spec, plan, résumés « Explique-moi » et rapports. Le code et les commits restent en anglais par convention, sauf si l'utilisateur demande autrement.
- **Applications générées bilingues en option**: case « App bilingue FR/EN » à la création du projet; les gabarits incluent alors l'i18n et les agents produisent les deux langues. Utile pour les entreprises québécoises qui doivent offrir leurs logiciels en français.
- D'autres langues pourront s'ajouter par la communauté (voir Traductions communautaires, section 17).

### Vues

- **Projets / Chat**: projets en dossiers (style Open WebUI), chat par projet, entrevue, spec, maquette, plan éditable.
- **Agents**: tableau Kanban des tâches (à faire, en cours, CI, fusionnée, bloquée), logs en direct, diff de chaque tâche, boutons pause/stop/relancer/escalader, file des questions à l'humain.
- **Démos**: aperçus par jalon, captures, bouton Valider / Commenter / Revenir.
- **Magasin**: cartes par type et catégorie, filtre « compatible avec ma machine », installation avec progression en direct, réglages générés depuis le manifeste.
- **Coûts**: budgets, tableau par projet/modèle, estimation vs réel.
- **Réglages**: nœuds, préréglages de modèles, clés d'API, utilisateurs, sauvegardes, mises à jour.
- **Assistant de premier lancement**: compte admin → détection matériel → pack de départ → clé d'API optionnelle → projet exemple guidé (« crée une liste de tâches »).
- PWA utilisable sur téléphone (valider une démo, répondre à une question d'agent).
- Notifications: ntfy, Discord, courriel, webhook générique.

## 13. Communauté et gouvernance

### Licence
- Noyau sous AGPL-3.0; SDK de modules, schéma de manifeste et gabarits de projet sous Apache-2.0 (voir Décisions). Chaque module du catalogue garde sa propre licence, affichée dans le magasin.
- Contributions sous **DCO** (Developer Certificate of Origin, signature `Signed-off-by`) plutôt qu'un CLA, plus simple pour les contributeurs.

### Fichiers du dépôt
`README` (FR/EN, captures, démarrage en 5 minutes), `CONTRIBUTING`, `CODE_OF_CONDUCT` (Contributor Covenant), `SECURITY`, `GOVERNANCE`, `ROADMAP`, `CHANGELOG`, gabarits d'issues et de PR, `CLAUDE.md` / `AGENTS.md` pour les contributeurs qui codent avec des agents.

### Pour les contributeurs
- **Environnement de dev en une commande** (`make dev` ou devcontainer) avec données de démo.
- **SDK de modules**: `cobble module init | lint | test | pack`, banc de test qui installe le module dans un Docker isolé avec le pack de base et vérifie les branchements. Un gabarit de dépôt avec la CI déjà prête pour les auteurs de modules.
- **Processus RFC** pour les changements majeurs (format des manifestes, API, schéma des tâches).
- Étiquettes `good first issue` et `help wanted`; ajouter un module au catalogue est la porte d'entrée naturelle.
- **Dogfooding**: Cobble sert à développer des modules et des gabarits pour Cobble.

### Partage dans la communauté
- **Classement des modèles locaux** (opt-in, anonyme): résultats du benchmark local par GPU et par modèle, publiés sur un tableau public. Répond à la question « quel modèle pour ma carte? ».
- **Gabarits de projet et profils d'agents** partagés via les catalogues.
- **Galerie** de projets construits avec la plateforme (opt-in).

### Télémétrie
- Désactivée par défaut, opt-in explicite, contenu documenté et consultable dans l'interface avant l'envoi.

### Publication
- SemVer, versions publiées par la CI avec images signées, notes de version bilingues.
- Documentation sur un site (MkDocs Material ou Starlight), FR/EN: installation, guides par profil matériel, création de modules, dépannage.
- Espace de discussion (GitHub Discussions + Discord ou Matrix).
- Financement: GitHub Sponsors ou Open Collective.

## 14. Feuille de route

Chaque version est utilisable de bout en bout. On prouve d'abord que la boucle idée → app fonctionne avec un pack fixe, puis on généralise. Construire tout le magasin avant d'avoir prouvé le cœur serait le piège principal.

### v0.1 — La boucle fonctionne (pack fixe)
- `install.sh` + CLI de base + noyau (Postgres, Redis, LiteLLM, Caddy, API, UI minimale avec login).
- Pack fixe codé en dur: Forgejo, Woodpecker, Ollama ou API, runner Aider.
- Chat → entrevue → spec → plan → tâches avec tests d'abord → agents → CI → fusion → démo.
- Un seul gabarit de projet (FastAPI + front simple).
- **Critère**: sur une VM Ubuntu vierge, une personne non technique installe, décrit une app de liste de tâches et obtient une démo fonctionnelle, CI verte, avec le coût affiché.

### v0.2 — Magasin et modules
- Module-manager complet: manifestes, capacités, résolution des dépendances, règles anti-conflit, hooks, coffre, retour en arrière.
- Le pack fixe de la v0.1 devient des modules du catalogue officiel; variantes Ollama CPU/NVIDIA/AMD.
- Onglet Magasin, packs de départ, assistant de premier lancement.
- SDK de modules (`init`, `lint`, `test`).
- **Critère**: installer et désinstaller chaque module dans n'importe quel ordre sans conflit; Forgejo + Woodpecker et Ollama + LiteLLM se branchent seuls.

### v0.3 — Coûts et fiabilité des agents
- Routeur de coûts complet (rôles, chaînes de repli, escalade, budgets, estimation, électricité).
- Benchmark local et préréglages de modèles.
- Garde-fous (boucles, durée), questions à l'humain, agent réviseur, leçons apprises.
- Onglet Agents complet (Kanban, diffs, logs en direct) et onglet Coûts.
- **Critère**: sur un jeu de 5 projets de référence, taux de réussite et coût moyen mesurés et publiés; aucun agent ne dépasse son budget.

### v0.4 — Ouverture
- Conteneurs custom (image, compose, manifeste), catalogues tiers, badge non vérifié.
- Gabarits de projet supplémentaires et profils d'agents dans le magasin.
- Import d'un dépôt existant; export (zip, GitHub, image Docker).
- Notifications, PWA.

### v0.5 — Multi-machines et sécurité renforcée
- Nœuds distants (`--node --join`), ordonnancement VRAM.
- Modules gVisor / Sysbox, proxy réseau en liste blanche pour les agents.
- Sauvegarde et restauration complètes, canaux stable/beta.

### v1.0 — Stable
- API v1 figée, format de manifeste v1 figé, documentation complète FR/EN, migrations testées depuis chaque version 0.x.
- Classement communautaire des modèles en ligne.
- Audit de sécurité externe ou revue communautaire.

### Après 1.0
- Multi-utilisateurs et rôles (OIDC / Authentik), portail client (le client voit sa démo et son coût).
- Serveur MCP pour piloter la plateforme depuis Claude Code ou un autre client MCP; accès des agents à des serveurs MCP (documentation de librairies).
- Déploiement en production des apps générées (LXC Proxmox, VPS, Coolify).
- Support arm64 (Raspberry Pi 5, Mac via VM).

## 15. Banc d'essai des agents

Pour mesurer les progrès sans débat d'opinions:
- 5 à 10 **projets de référence** (liste de tâches, blogue, API de facturation, tableau de bord, bot) avec specs figées et tests cachés.
- À chaque version, la CI du projet roule le banc avec les préréglages « Économique local » et « Équilibré » et publie: taux de réussite, coût, durée, nombre d'escalades.
- Ce banc sert aussi à valider qu'un changement de prompt ou de modèle améliore vraiment les résultats.

## 16. Décisions

| Sujet | Choix | Raison |
|---|---|---|
| **Nom** | **Cobble** (de « cobble together »: assembler une app avec des pièces simples) | Court, facile en CLI (`cobble install`), aucun conflit trouvé dans le créneau des agents de code. « DevFactory » écarté (déjà pris par une entreprise de logiciels). |
| **Licence du noyau** | **AGPL-3.0** | Empêche qu'un tiers reprenne Cobble pour en faire un service fermé. N'empêche pas l'usage commercial, et le code des applications générées appartient à l'utilisateur. |
| **Licence du SDK, du schéma de manifeste et des gabarits de projet** | **Apache-2.0** | Les auteurs de modules et les applications générées à partir des gabarits restent libres de toute obligation copyleft. |
| **Contributions** | **DCO** (`Signed-off-by`), pas de CLA | Plus simple pour les contributeurs. Conséquence: la licence du noyau ne pourra pas être changée facilement plus tard. |
| **Frontend** | **Maison, React + Vite + TypeScript** | Plus grand bassin de contributeurs, et bien généré par les modèles de code. Pas de fork d'Open WebUI (licence avec restrictions de marque). |
| **Git par défaut** | **Forgejo** | Gouvernance communautaire, API complète, léger. Gitea offert comme module alternatif. |
| **CI par défaut** | **Woodpecker** | Léger, branchement OAuth avec Forgejo simple. Forgejo Actions offert comme module alternatif. |
| **Runner d'agents** | **Aider** en v0.1, **OpenHands** comme module ensuite | Aider est simple et fonctionne en mode headless; les autres runners deviennent des modules. |
| **Module-manager** | **Python** | Une seule pile pour tout le noyau, plus facile pour les contributeurs. Réévaluer Go seulement si la distribution ou la performance l'exigent. |
| **Pile du noyau** | FastAPI, Postgres, Redis, LiteLLM, Caddy | Voir section 4. |

### Reste à faire avant le premier commit public
- **Réserver le nom**: organisation GitHub, domaine (ex.: cobble.dev, getcobble.dev, cobble.sh), noms de paquets PyPI et npm.
- **Vérifier les marques**: OPIC (Canada), USPTO (États-Unis), EUIPO (Europe). La vérification faite jusqu'ici n'est qu'une recherche web superficielle.
- **Licences des modules**: vérifier chacune avant l'ajout au catalogue officiel. S'inspirer du format des app stores d'Umbrel, CasaOS ou Runtipi sans réutiliser leur code avant d'avoir vérifié leur licence (celle d'umbrelOS n'est pas une licence open source classique).
- Logo et identité visuelle simples (thème: pavés, pièces assemblées).

## 17. Idées additionnelles

Chaque idée indique la version où elle s'intègre. Elles s'ajoutent à la feuille de route (section 14) sans en changer l'ordre.

> **Portée gelée (2026-10-30).** Aucune nouvelle idée n'entre dans le plan avant la sortie de la v0.1. Les nouvelles idées vont dans les issues du dépôt avec l'étiquette `idée`, et sont triées à chaque version.

### Rendre l'expérience encore plus simple

| Idée | Description | Version |
|---|---|---|
| **Pointer et commenter** | Dans l'aperçu de la démo, l'utilisateur clique sur un élément et écrit « mets ce bouton en bleu » ou « ce total est faux ». Cobble capture l'élément, la page et la capture d'écran, retrouve le fichier source et crée une tâche ciblée. Plus besoin de décrire où se trouve le problème. | v0.4 |
| **Entrée vocale** | Module Whisper local pour dicter dans le chat (utile sur téléphone ou sur le terrain). Aucun audio ne sort de la machine. | v0.4 |
| **Croquis ou capture → maquette** | L'utilisateur envoie une photo d'un croquis papier ou une capture d'une app qu'il aime; le planner s'en sert pour la maquette (modèle avec vision). | v0.4 |
| **Variantes de maquette** | Pour quelques sous, le planner propose 2 ou 3 maquettes différentes; l'utilisateur choisit avant que le code commence. | v0.3 |
| **Données de démo réalistes** | Un agent génère des données d'exemple crédibles pour que la démo soit vraiment testable (pas une liste vide). | v0.1 |
| **Mode « Explique-moi »** | À chaque jalon, un résumé en langage simple de ce qui a été construit et pourquoi. L'utilisateur apprend en chemin; utile pour la communauté débutante. | v0.3 |

### Réduire encore les coûts

| Idée | Description | Version |
|---|---|---|
| **Prix à jour** | Table des prix des modèles mise à jour automatiquement; le routeur choisit le modèle le moins cher qui atteint le niveau de qualité requis et avertit si un prix change. | v0.3 |
| **Paliers gratuits** | Utilisation des modèles gratuits offerts par certains fournisseurs (ex.: modèles gratuits d'OpenRouter), avec respect des limites de débit et des conditions d'utilisation de chaque fournisseur. | v0.3 |
| **Indicateur de VRAM** | Dans le magasin, chaque modèle local affiche s'il rentre dans la mémoire du GPU (vert/jaune/rouge) et suggère la bonne quantification. | v0.2 |
| **Reprise après panne** | Les tâches sont enregistrées par étapes; après un redémarrage ou une coupure, le travail reprend là où il était au lieu de recommencer et de repayer les tokens. | v0.3 |

### Confidentialité

| Idée | Description | Version |
|---|---|---|
| **Projet « local seulement »** | Option par projet qui interdit tout appel à une API externe; le routeur n'utilise que les modèles locaux. Pour du code confidentiel (client industriel, données internes). | v0.3 |
| **Masquage avant envoi** | Avant tout appel à un modèle externe, un filtre retire les secrets, mots de passe, adresses IP internes et renseignements personnels détectés, puis les remet dans la réponse. | v0.5 |

### Après la livraison

| Idée | Description | Version |
|---|---|---|
| **Maintenance continue** | Cobble surveille les dépendances des apps livrées, rejoue les tests et crée seul des tâches de mise à jour de sécurité. L'app ne pourrit pas après la livraison. | v0.5 |
| **Bouton « Signaler un bogue »** | Widget optionnel intégré aux apps générées: l'utilisateur final signale un bogue (capture + console) et ça devient directement une tâche dans Cobble. | v0.5 |
| **Rapport de fin de projet** | Export PDF: fonctionnalités livrées, architecture, coût réel vs estimé, temps, modèles utilisés, instructions de déploiement. Utile pour livrer à un client. | v0.4 |
| **Licence de l'app et des dépendances** | L'utilisateur choisit la licence de son app à la création; la CI vérifie que les licences des dépendances sont compatibles. | v0.4 |

### Qualité

| Idée | Description | Version |
|---|---|---|
| **Accessibilité des apps générées** | Vérification automatique (axe-core) dans la CI des gabarits web; les agents corrigent les problèmes comme n'importe quel test qui échoue. | v0.4 |
| **Accessibilité de Cobble** | Interface utilisable au clavier et avec un lecteur d'écran, contrastes conformes WCAG AA. | v0.2 |
| **Tests de performance de base** | Temps de chargement et temps de réponse des API mesurés dans la CI; une régression importante bloque la fusion. | v0.5 |

### Communauté

| Idée | Description | Version |
|---|---|---|
| **Projet → gabarit** | Un projet terminé peut être exporté comme gabarit de projet et publié dans un catalogue. La communauté enrichit le magasin en construisant des apps. | v0.4 |
| **Remix** | Partir d'un projet de la galerie communautaire et le modifier au lieu de partir de zéro. | v1.0 |
| **Gabarits spécialisés** | Gabarits pour des créneaux où Cobble peut se démarquer: domotique (intégrations Home Assistant), IoT et industriel (tableaux de bord MQTT, lecture Modbus TCP, client OPC UA), outils internes de PME (inventaire, bons de travail, calendrier d'entretien). | v0.4 |
| **Défis communautaires** | Défi mensuel (« construis un outil de gestion de bénévoles ») avec résultats publiés: coût, modèles utilisés, temps. Fait connaître le projet et alimente le banc d'essai. | v1.0 |
| **Traductions communautaires** | Interface et documentation traduites via une plateforme libre (ex.: Weblate), au-delà du français et de l'anglais. | v1.0 |

### Outillage, énergie et exploitation

| Idée | Description | Version |
|---|---|---|
| **Faux fournisseur LLM** | Module `llm` qui rejoue des réponses enregistrées (cassettes). Permet de développer et tester Cobble sans GPU ni clé d'API, et rend la CI du projet gratuite et déterministe. | v0.1 |
| **Compteur d'économies** | Pour chaque projet: coût réel vs coût estimé si tout avait été fait avec le modèle le plus fort. Affiché dans l'onglet Coûts et dans le rapport de fin de projet. | v0.3 |
| **Cache local des paquets** | Modules Verdaccio (npm) et devpi (PyPI): installations plus rapides pour les agents, fonctionnement hors ligne, moins de bande passante. Branchés automatiquement aux runners. | v0.3 |
| **Documentation hors ligne pour les agents** | Module DevDocs ou Kiwix: les agents consultent la documentation des librairies au lieu d'inventer des fonctions. | v0.4 |
| **Issues → tâches** | Une issue ouverte dans le dépôt Forgejo d'un projet (étiquette `cobble`) entre automatiquement dans le backlog des agents. | v0.4 |
| **Mode expert** | Interrupteur dans les réglages: voir et modifier les prompts des agents, forcer un modèle sur une tâche, ajuster les garde-fous. Désactivé par défaut. | v0.4 |
| **Wake-on-LAN des nœuds** | Quand des tâches attendent, Cobble réveille le nœud GPU, puis le laisse retourner en veille quand la file est vide. Les modèles sont déchargés automatiquement après inactivité. | v0.5 |
| **Sauvegardes externes** | Module restic: sauvegardes chiffrées et planifiées vers un NAS, S3 ou Backblaze B2, configurées depuis l'interface, avec test de restauration. | v0.5 |

## 18. Règles pour Claude Code

- Travailler version par version; ne pas commencer la suivante avant que le critère de la précédente soit vérifié.
- Intégrer les idées de la section 17 dans la version indiquée; ne pas les devancer.
- Le noyau ne référence jamais un module par son nom, seulement par capacité. En v0.1, le pack fixe passe déjà par cette interface même s'il est codé en dur.
- Les règles anti-conflit sont appliquées par le module-manager, jamais confiées aux manifestes.
- Toute chaîne visible dans l'UI passe par les fichiers i18n (FR et EN).
- Tests: unitaires (orchestrateur, ordonnanceur, routeur de coûts, validation des manifestes, résolution des dépendances), intégration (installation du pack dans Docker-in-Docker), installateur (VM Ubuntu 24.04/26.04, Debian 12/13), et le banc d'essai des agents.
- Migrations de base de données pour tout changement de schéma, testées dans les deux sens.
- Commits petits, un par fonctionnalité, signés DCO. Mettre `CHANGELOG.md` à jour.
- Tenir `CLAUDE.md` à jour avec les conventions du dépôt au fur et à mesure.
