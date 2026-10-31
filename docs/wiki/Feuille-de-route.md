# Feuille de route / Roadmap

**Français** · [English](#english)

| Version | Contenu | État |
|---|---|---|
| **v0.1** | La boucle fonctionne avec un pack fixe: installateur, chat → spec → plan → agents → CI → démo, coûts | code complet; **validation réelle à faire** |
| v0.2 | Magasin et modules (Forgejo, Woodpecker, Ollama deviennent des modules), packs de départ, assistant de premier lancement, SDK de modules | à venir |
| v0.3 | Routeur de coûts complet (chaînes de repli, benchmark local), agent réviseur, questions à l'humain, banc d'essai | à venir |
| v0.4 | Conteneurs et catalogues personnalisés, import/export de dépôts, notifications, PWA | à venir |
| v0.5 | Nœuds distants (GPU), isolation renforcée (gVisor), sauvegarde et restauration | à venir |
| v1.0 | API et manifestes figés, documentation complète, audit de sécurité | à venir |

Le plan complet est dans [PLAN.md](https://github.com/Installation-04/Cobble/blob/main/PLAN.md). Les idées hors portée vont dans une issue avec l'étiquette `idée`.

## Ce qui reste pour la v0.1

1. Valider sur une VM Ubuntu vierge avec une vraie clé d'API économique (protocole dans [`docs/releases/v0.1.md`](https://github.com/Installation-04/Cobble/blob/main/docs/releases/v0.1.md)).
2. Lancer une fois `make e2e-full` (chaîne réelle complète).
3. Activer l'application GitHub « DCO » sur le dépôt.

---

## English

v0.1 (a fixed pack: installer, chat → spec → plan → agents → CI → demo, costs): code complete, **real validation still to do**. v0.2: store and modules, starter packs, first-run wizard, module SDK. v0.3: full cost router (fallback chains, local benchmark), reviewer agent, questions to the human, benchmark suite. v0.4: custom containers and catalogs, repo import/export, notifications, PWA. v0.5: remote nodes (GPU), hardened isolation (gVisor), backup and restore. v1.0: frozen API and manifests, complete docs, security audit. Full plan: [PLAN.md](https://github.com/Installation-04/Cobble/blob/main/PLAN.md). Remaining for v0.1: validate on a clean Ubuntu VM with a real inexpensive API key, run `make e2e-full` once, enable the GitHub "DCO" app.
