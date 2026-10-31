# FAQ and troubleshooting

**English** · [Français](#français)

**`cobble doctor` reports a problem.** It checks Docker, the containers, `/api/v1/health`, disk, ports, `.env` permissions and the systemd unit, and suggests a fix for each failure.

**I lost the admin password.** `cobble reset-admin` closes the sessions and prints a new link: you change the email and password, and **your projects are kept**.

**The project is "paused".** The budget is reached. Raise it in the API (`PATCH /projects/{id}` with `budget_usd`) above the spend and the project resumes.

**A task is "blocked" or "failed".** A task fails after several attempts (the later ones escalated to a stronger model); its dependents are then blocked. Open it in the Agents tab (log, diff), then **Retry**.

**Building images fails with a certificate error.** TLS-inspecting network: pass your CA bundle as the `ca` build secret (see `docs/en/dev.md`).

**The installer refuses my machine.** Only Ubuntu 24.04/26.04 and Debian 12/13 on amd64 are supported; `--skip-checks` only relaxes the resource checks.

**Can I use local models (Ollama)?** Not in the v0.1 pack (hosted model APIs only). It is planned for the next version (modules).

**Where is the data?** In the Docker volumes `cobble-*` (Postgres, Redis, Caddy) and in `/opt/cobble/.env` (secrets, mode 0600).

---

## Français

**`cobble doctor` signale un problème.** Il vérifie Docker, les conteneurs, `/api/v1/health`, le disque, les ports, les permissions de `.env` et le service systemd, et propose un correctif pour chaque échec.

**J'ai perdu le mot de passe admin.** `cobble reset-admin` ferme les sessions et affiche un nouveau lien: vous changez le courriel et le mot de passe, **vos projets sont conservés**.

**Le projet est « en pause ».** Le budget est atteint. Remontez-le dans l'API (`PATCH /projects/{id}` avec `budget_usd`) au-dessus de la dépense: le projet repart.

**Une tâche est « bloquée » ou « échouée ».** Une tâche échoue après plusieurs tentatives (la deuxième moitié escaladée vers un modèle plus fort); ses dépendantes sont alors bloquées. Ouvrez-la dans l'onglet Agents (journal, diff), puis **Relancer**.

**Le build d'images échoue avec une erreur de certificat.** Réseau avec inspection TLS: passez votre bundle CA comme secret de build `ca` (voir `docs/fr/dev.md`).

**L'installateur refuse ma machine.** Seuls Ubuntu 24.04/26.04 et Debian 12/13 en amd64 sont pris en charge; `--skip-checks` assouplit seulement les contrôles de ressources.

**Puis-je utiliser des modèles locaux (Ollama) ?** Pas dans le pack de la v0.1 (API de modèles seulement). C'est prévu dans la version suivante (modules).

**Où sont les données ?** Volumes Docker `cobble-*` (Postgres, Redis, Caddy) et `/opt/cobble/.env` (secrets, mode 0600).
