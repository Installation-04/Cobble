# Cobble agent-service: the ONE component allowed to hold the Docker socket (CLAUDE.md rule 5,
# ADR 0006). It runs as an unprivileged user that joins the socket's group (compose `group_add`).
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 PYTHONPATH=/app PATH=/opt/venv/bin:$PATH
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Optional build secret "ca": a CA bundle for networks with TLS inspection.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --locked --no-dev --no-install-project
COPY cobble_agent_service ./cobble_agent_service
# /data holds the run directories. A fresh named volume inherits this ownership.
RUN useradd --system --uid 10001 --no-create-home agent \
    && mkdir /data && chown 10001:10001 /data
USER 10001
EXPOSE 8090
CMD ["uvicorn", "cobble_agent_service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090"]
