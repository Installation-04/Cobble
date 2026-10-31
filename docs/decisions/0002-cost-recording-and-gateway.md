# 0002 — Cost recording and the model gateway

Status: accepted (v0.1, step 2)

- **Where costs are stored**: in Cobble's own `llm_calls` table, written by Cobble's gateway after each LiteLLM call (tokens from `usage`, cost from the `x-litellm-response-cost` header). LiteLLM's own spend database is not used: it would need a second database and Prisma, and the cost router (step 4) needs per-project and per-task attribution that LiteLLM does not know about.
- **Fake provider pricing**: the fake model has fictional per-token prices in `core/litellm/config.yaml`, so cost recording is observable without any real spend.
- **No public chat route**: authentication arrives in step 3, so the step-2 demo is the CLI (`python -m cobble.cli chat`, `make smoke`) and integration tests, not an unauthenticated HTTP endpoint.
- **Gateway location**: `cobble/router/gateway.py`. It becomes the `LLMClient` capability implementation in step 4.
- **Test overlay**: `core/compose.test.yml` publishes Postgres, Redis and LiteLLM on 127.0.0.1 for host-side integration tests only. Docker publishes ports only for containers on a non-internal network, so the overlay attaches them to `edge`. The real stack publishes Caddy's port only (checked by `test_stack_invariants.py`).
- **Build behind a TLS-inspecting proxy**: the Dockerfiles accept an optional build secret `ca` (a CA bundle); see `docs/en/dev.md`.
