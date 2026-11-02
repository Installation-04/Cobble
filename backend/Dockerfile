# Static Docker CLI and compose plugin, for the module-manager image only (pinned by digest).
FROM docker:27-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c AS docker-cli

FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 PYTHONPATH=/app PATH=/opt/venv/bin:$PATH
WORKDIR /app
# The module SDK (Apache-2.0) is a path dependency (../sdk from /app): compose passes it as the
# named build context `sdk`.
COPY --from=sdk pyproject.toml uv.lock LICENSE /sdk/
COPY --from=sdk cobble_sdk /sdk/cobble_sdk
# git: the worker pushes the project template to the Git provider through the git binary.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
# Optional build secret "ca": a CA bundle for networks with TLS inspection.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY cobble ./cobble
RUN useradd --system --uid 10001 --no-create-home cobble \
    # Where the module-manager keeps its vault master key (a named volume inherits this owner).
    && mkdir -p /var/lib/cobble-keys /var/lib/cobble-routes \
    && chown 10001:10001 /var/lib/cobble-keys /var/lib/cobble-routes \
    && chmod 700 /var/lib/cobble-keys && chmod 755 /var/lib/cobble-routes
USER 10001

# The module-manager: this image plus the Docker CLI and compose plugin. It is the only image that
# is given the Docker socket and the vault master key (CLAUDE.md rule 5).
FROM base AS module-manager
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose \
    /usr/local/libexec/docker/cli-plugins/docker-compose
ENV HOME=/tmp DOCKER_CONFIG=/tmp/.docker
CMD ["python", "-m", "cobble.module_manager"]

# The default target: the API and the worker.
FROM base AS backend
CMD ["uvicorn", "cobble.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
