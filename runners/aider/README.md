# Cobble agent runner (Aider)

**Français** · [English](#english)

Image du conteneur d'agent v0.1: Aider 0.86.2 (verrouillé, `uv.lock`), git, uv, Node 22 + pnpm 10.28.
Utilisateur uid 10001, répertoire de travail `/work` (le worktree monté par agent-service), système de
fichiers racine en lecture seule, aucun identifiant git, aucun socket Docker. Voir `docs/fr/agents.md`.

- `entrypoint` (`cobble-agent`): lit `COBBLE_MARKER`, `COBBLE_INSTRUCTIONS_FILE`, `COBBLE_FILES`,
  `COBBLE_TEST_COMMAND`, `COBBLE_MAX_ITERATIONS`, `COBBLE_MODEL`, `OPENAI_API_BASE`, `OPENAI_API_KEY`
  (jeton d'exécution); lance Aider sans interface; code de sortie 0 = terminé et tests locaux verts.
  `COBBLE_AGENT_CMD` remplace Aider par une commande shell (tests seulement).
- `test-wrapper` (`cobble-test`): exécute la commande de test et écrit des lignes lisibles par machine.
- Construire: `docker build -t cobble-aider-runner:0.1 runners/aider` (secret facultatif `--secret id=ca,src=ca.crt`).
- Mettre à jour Aider: changer la version dans `pyproject.toml`, puis `uv lock`.

## English

Image of the v0.1 agent container: Aider 0.86.2 (locked, `uv.lock`), git, uv, Node 22 + pnpm 10.28.
Runs as uid 10001 with `/work` (the worktree mounted by agent-service) as working directory, a read-only
root filesystem, no git credentials and no Docker socket. See `docs/en/agents.md`.

- `entrypoint` (`cobble-agent`): reads `COBBLE_MARKER`, `COBBLE_INSTRUCTIONS_FILE`, `COBBLE_FILES`,
  `COBBLE_TEST_COMMAND`, `COBBLE_MAX_ITERATIONS`, `COBBLE_MODEL`, `OPENAI_API_BASE`, `OPENAI_API_KEY`
  (the run token); runs Aider headless; exit code 0 = finished and local tests green.
  `COBBLE_AGENT_CMD` replaces Aider with a shell command (tests only).
- `test-wrapper` (`cobble-test`): runs the test command and prints machine-readable lines.
- Build: `docker build -t cobble-aider-runner:0.1 runners/aider` (optional `--secret id=ca,src=ca.crt`).
- Upgrade Aider: change the version in `pyproject.toml`, then `uv lock`.
