# Development stack

```bash
make dev          # generates core/.env (random secrets), builds and starts everything
make smoke        # one chat request through LiteLLM to the fake provider + the recorded row
make dev-logs     # follow logs
make dev-down     # stop (data volumes are kept)
```

No API key is needed: LiteLLM routes the `fake` model to the fake provider, which replays cassettes from `providers/fake-llm/cassettes/`.

Open `http://localhost:8080` (health check: `/api/v1/health`). Only Caddy publishes a port; change it with `COBBLE_HTTP_PORT` in `core/.env`.

| Service | Role |
|---|---|
| `caddy` | Only published port; routes `/api/*` to the API, the rest to the UI |
| `api` | FastAPI; runs Alembic migrations at startup |
| `worker` | Consumes the Redis event stream |
| `litellm` | Model gateway (pinned version) |
| `fake-llm` | OpenAI-compatible provider replaying cassettes |
| `postgres`, `redis` | State and event bus |
| `ui` | Placeholder page (the React UI arrives in step 3) |

## Tests

- `make test`: unit tests (no services needed).
- `make test-integration`: starts the stack with `core/compose.test.yml` (ports on 127.0.0.1 only) and runs the integration tests: migrations up and down on real Postgres, real health check, and the full chat → LiteLLM → cassette → database chain.

## Behind a proxy that inspects TLS

Image builds fail with certificate errors on such networks. Pass your CA bundle as the optional `ca` build secret through an extra compose file:

```yaml
# my-ca.yml
services:
  api: { build: { secrets: [ca] } }
  worker: { build: { secrets: [ca] } }
  fake-llm: { build: { secrets: [ca] } }
secrets:
  ca: { file: /path/to/ca-bundle.crt }
```

```bash
make dev COMPOSE_FLAGS="-f my-ca.yml"
```

If BuildKit asks for filesystem privileges, set `BUILDX_BAKE_ENTITLEMENTS_FS=0`.
