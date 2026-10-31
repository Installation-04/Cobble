# FAQ et dépannage / FAQ and troubleshooting

**Français** · [English](#english)

**`cobble doctor` signale un problème.** Il vérifie Docker, les conteneurs, `/api/v1/health`, le disque, les ports, les permissions de `.env` et le service systemd, et propose un correctif pour chaque échec.

**J'ai perdu le mot de passe admin.** `cobble reset-admin` ferme les sessions et affiche un nouveau lien: vous changez le courriel et le mot de passe, **vos projets sont conservés**.

**Le projet est « en pause ».** Le budget est atteint. Remontez-le dans l'API (`PATCH /projects/{id}` avec `budget_usd`) au-dessus de la dépense: le projet repart.

**Une tâche est « bloquée » ou « échouée ».** Une tâche échoue après plusieurs tentatives (la deuxième moitié escaladée vers un modèle plus fort); ses dépendantes sont alors bloquées. Ouvrez-la dans l'onglet Agents (journal, diff), puis **Relancer**.

**Le build d'images échoue avec une erreur de certificat.** Réseau avec inspection TLS: passez votre bundle CA comme secret de build `ca` (voir `docs/fr/dev.md`).

**L'installateur refuse ma machine.** Seuls Ubuntu 24.04/26.04 et Debian 12/13 en amd64 sont pris en charge; `--skip-checks` assouplit seulement les contrôles de ressources.

**Puis-je utiliser des modèles locaux (Ollama) ?** Pas dans le pack de la v0.1 (API de modèles seulement). C'est prévu dans la version suivante (modules).

**Où sont les données ?** Volumes Docker `cobble-*` (Postgres, Redis, Caddy) et `/opt/cobble/.env` (secrets, mode 0600).

---

## English

**`cobble doctor` reports a problem**: it checks Docker, containers, `/api/v1/health`, disk, ports, `.env` permissions and the systemd unit, with a fix for each failure. **Lost the admin password**: `cobble reset-admin` prints a new link; **projects are kept**. **Project "paused"**: the budget is reached; raise `budget_usd` above the spend. **Task blocked/failed**: it failed after several attempts (later ones escalated to a stronger model) and its dependents are blocked; inspect it in the Agents tab, then **Retry**. **Certificate errors while building images**: TLS-inspecting network, pass your CA bundle as the `ca` build secret (`docs/en/dev.md`). **Installer refuses my machine**: only Ubuntu 24.04/26.04 and Debian 12/13 on amd64; `--skip-checks` only relaxes resource checks. **Local models (Ollama)?** Not in the v0.1 pack (hosted model APIs only); planned for the next version. **Where is the data?** Docker volumes `cobble-*` and `/opt/cobble/.env` (mode 0600).
