# Cobble agent runner: Aider + the build tooling of a generated project (python/uv,
# node/pnpm). It runs on the internal network `cobble_agents` as an unprivileged user with a
# read-only root filesystem (the worktree mounted on /work and /tmp are the only writable
# places). It holds no git credentials and no Docker socket (see docs/en/agents.md).
FROM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS node

# Build context "template": the generated-project template (compose additional_contexts). The
# empty fallback keeps a plain `docker build` working; the cache is then simply not pre-warmed.
FROM scratch AS template

FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /uvx /usr/local/bin/

# UV_PROJECT_ENVIRONMENT is deliberately NOT set globally: the project's own `uv run` must use
# its .venv, not Aider's read-only environment.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 COREPACK_HOME=/opt/corepack

# git (aider commits locally; agent-service pushes) and a CA bundle for registry TLS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node + corepack come from the official image, pinned by digest.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack

# Aider, from the lock file (exact versions and hashes).
WORKDIR /opt/aider-src
COPY pyproject.toml uv.lock ./
# Optional build secret "ca": a CA bundle for networks with TLS inspection.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then \
      export SSL_CERT_FILE=/run/secrets/ca REQUESTS_CA_BUNDLE=/run/secrets/ca \
             PIP_CERT=/run/secrets/ca NODE_EXTRA_CA_CERTS=/run/secrets/ca; \
    fi; \
    UV_PROJECT_ENVIRONMENT=/opt/aider uv sync --locked --no-dev --no-install-project \
    && corepack enable pnpm \
    && corepack prepare pnpm@10.28.0 --activate \
    && chmod -R a+rX /opt/aider /opt/corepack

# Pre-warm a uv cache with the template's locked dependencies, so a project's tests run without
# reaching the package registry (faster, cheaper, works when egress is restricted). The
# entrypoint copies it into the writable /tmp. Other dependencies still use the allow-listed proxy.
COPY --from=template / /opt/template-seed/
RUN --mount=type=secret,id=ca,required=false \
    set -e; \
    if [ -f /opt/template-seed/uv.lock ]; then \
      if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
      cd /opt/template-seed \
      && UV_CACHE_DIR=/opt/uv-seed UV_PROJECT_ENVIRONMENT=/tmp/seed-venv \
         uv sync --locked --no-install-project \
      && rm -rf /tmp/seed-venv /opt/template-seed; \
    fi; \
    mkdir -p /opt/uv-seed && chmod -R a+rX /opt/uv-seed

# Same for the frontend: pre-fetch the template's pnpm store from its lockfile.
RUN --mount=type=secret,id=ca,required=false \
    --mount=type=bind,from=template,target=/seed \
    set -e; \
    if [ -f /seed/frontend/pnpm-lock.yaml ]; then \
      if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca SSL_CERT_FILE=/run/secrets/ca; fi; \
      mkdir /tmp/fe && cp /seed/frontend/package.json /seed/frontend/pnpm-lock.yaml /tmp/fe/ \
      && cd /tmp/fe && COREPACK_HOME=/opt/corepack pnpm fetch --store-dir /opt/pnpm-seed \
      && rm -rf /tmp/fe; \
    fi; \
    mkdir -p /opt/pnpm-seed && chmod -R a+rX /opt/pnpm-seed

COPY entrypoint /usr/local/bin/cobble-agent
COPY test-wrapper /usr/local/bin/cobble-test
RUN chmod 0755 /usr/local/bin/cobble-agent /usr/local/bin/cobble-test \
    && useradd --uid 10001 --user-group --no-create-home --home-dir /tmp/home --shell /usr/sbin/nologin agent \
    && mkdir /work && chown 10001:10001 /work

ENV HOME=/tmp/home PATH=/opt/aider/bin:$PATH UV_CACHE_DIR=/tmp/cache/uv \
    npm_config_cache=/tmp/cache/npm PNPM_HOME=/tmp/cache/pnpm npm_config_store_dir=/tmp/cache/pnpm-store XDG_CACHE_HOME=/tmp/cache \
    GIT_TERMINAL_PROMPT=0 AIDER_ANALYTICS_DISABLE=1 LITELLM_LOCAL_MODEL_COST_MAP=True
WORKDIR /work
USER 10001
ENTRYPOINT ["/usr/local/bin/cobble-agent"]
