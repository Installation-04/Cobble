# Cobble fake LLM

**Français** · [English](#english)

Faux fournisseur LLM compatible OpenAI (`/v1/chat/completions`, `/v1/models`, streaming SSE) qui **rejoue des cassettes**. Il permet de développer et de tester Cobble sans GPU ni clé d'API; les tests n'appellent jamais un vrai modèle.

### Cassettes

Un fichier JSON par cassette dans `cassettes/`. La clé est le SHA-256 du modèle et des messages (rôle + texte). Une cassette sans clé explicite la calcule à partir de sa requête.

```json
{
  "version": 1,
  "request": { "model": "fake", "messages": [{ "role": "user", "content": "hello" }] },
  "response": { "content": "…", "finish_reason": "stop" }
}
```

- `{"version": 1, "default": true, "response": {...}}`: réponse par défaut, utilisée seulement si `FAKE_LLM_ALLOW_DEFAULT=1` (le cas de `make dev`).
- Sans cassette ni défaut, le serveur répond 404 `cassette_not_found` avec la clé manquante (mode strict, utilisé par les tests).
- Les jetons sont comptés par mots (déterministe) sauf si la cassette fournit `prompt_tokens` et `completion_tokens`.

### Réenregistrer (`make cassettes`)

`FAKE_LLM_MODE=record` relaie les requêtes inconnues vers un vrai fournisseur (`FAKE_LLM_UPSTREAM_URL`, `FAKE_LLM_UPSTREAM_API_KEY`) et écrit la cassette. Les clés, jetons et mots de passe sont **retirés automatiquement** avant l'écriture; la clé d'API amont n'est jamais stockée. Relire le diff d'une cassette avant de la commiter.

---

## English

OpenAI-compatible fake LLM provider (`/v1/chat/completions`, `/v1/models`, SSE streaming) that **replays cassettes**. It lets Cobble be developed and tested without a GPU or API key; tests never call a real model.

### Cassettes

One JSON file per cassette in `cassettes/`. The key is the SHA-256 of the model and messages (role + text). A cassette without an explicit key computes it from its request. See the example above.

- `{"version": 1, "default": true, "response": {...}}`: fallback reply, used only when `FAKE_LLM_ALLOW_DEFAULT=1` (what `make dev` does).
- With no matching or default cassette the server answers 404 `cassette_not_found` with the missing key (strict mode, used by tests).
- Tokens are counted by words (deterministic) unless the cassette provides `prompt_tokens` and `completion_tokens`.

### Re-recording (`make cassettes`)

`FAKE_LLM_MODE=record` forwards unknown requests to a real provider (`FAKE_LLM_UPSTREAM_URL`, `FAKE_LLM_UPSTREAM_API_KEY`) and writes the cassette. Keys, tokens and passwords are **scrubbed automatically** before writing; the upstream API key is never stored. Review a cassette's diff before committing it.
